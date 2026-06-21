"""Web demo for the Business Knowledge Assistant.

A thin Streamlit wrapper over the same pipeline as the CLI. It shows the full
flow for each question: routing, the generated SQL and rows, the retrieved PDF
pages, the answer with citations, and the citation check.

Run locally:   streamlit run app.py
Secrets used (Streamlit Cloud -> App -> Settings -> Secrets):
    ANTHROPIC_API_KEY = "sk-ant-..."
    APP_PASSWORD      = "something-you-share-with-the-viewer"   # optional gate
"""
from __future__ import annotations

import os

import streamlit as st

st.set_page_config(page_title="Business Knowledge Assistant", page_icon="🔎",
                   layout="wide")

# --- credentials -------------------------------------------------------------
# st.secrets raises if no secrets.toml exists at all (e.g. local runs that use a
# .env instead), so read it defensively and fall back to the environment.
def secret(key: str, default: str = "") -> str:
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.environ.get(key, default)


# Streamlit secrets are not exported to os.environ automatically; the Anthropic
# client reads ANTHROPIC_API_KEY from the environment, so copy it over.
_key = secret("ANTHROPIC_API_KEY")
if _key and not os.environ.get("ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = _key

APP_PASSWORD = secret("APP_PASSWORD", "")
MAX_QUERIES = int(secret("MAX_QUERIES", "25"))


# --- one-time data build -----------------------------------------------------
@st.cache_resource(show_spinner="Preparing sample data...")
def _ensure_data() -> dict:
    """Make sure the sample data exists. On the deployed app the DB and the
    parsed corpus cache are committed, so this is a no-op and nothing heavy
    (reportlab / pdfplumber) is imported at runtime."""
    from assistant import config, doc_retriever

    if not config.DB_PATH.exists():
        from data import build_database
        build_database.build()
    if not doc_retriever.CORPUS_JSON.exists():
        from data import generate_pdfs
        generate_pdfs.build()
    return doc_retriever.corpus_stats()


# --- password gate -----------------------------------------------------------
def _gate() -> bool:
    if not APP_PASSWORD:
        return True
    if st.session_state.get("authed"):
        return True
    st.title("Business Knowledge Assistant")
    st.caption("Enter the access code to try the demo.")
    code = st.text_input("Access code", type="password")
    if st.button("Enter"):
        if code == APP_PASSWORD:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Incorrect code.")
    return False


SAMPLE_QUESTIONS = [
    "What contracts expire in the next 90 days and what penalties are defined "
    "in those contracts?",
    "Which customers have overdue payments and what does the agreement say "
    "about service suspension?",
    "Show all active projects and summarize the risks mentioned in their "
    "documentation.",
    "Compare the penalty terms in the Riverstone and Cobalt contracts.",
    "Which customer with an overdue payment should we suspend first, based on "
    "the agreements?",
    "אילו חוזים פגי תוקף ב-90 הימים הקרובים ומהם הקנסות המוגדרים בהם?",
]


def _render(trace) -> None:
    from assistant.synthesizer import CITATION_RE  # noqa: F401

    r = trace.route
    st.subheader("1. Routing decision")
    intent = getattr(r, "intent", "")
    if intent:
        st.write(f"**Intent:** {intent}")
    st.write(f"**Sources:** {' + '.join(r.sources)}")
    if r.doc_query:
        st.write(f"**Document query:** {r.doc_query}")
    st.write(f"**Why:** {r.reasoning}")

    if trace.sql is not None:
        st.subheader("2. Structured retrieval (SQLite)")
        st.code(trace.sql.sql, language="sql")
        if trace.sql.error:
            st.error(trace.sql.error)
        else:
            st.caption(f"{len(trace.sql.rows)} row(s)")
            rows = [{"citation": item["cite"], **item["data"]}
                    for item in trace.sql.cited_rows()]
            if rows:
                st.dataframe(rows, use_container_width=True, hide_index=True)
            if trace.sql.document_files():
                st.caption("Linked documents (entity match): "
                           + ", ".join(trace.sql.document_files()))

    if trace.route.needs_docs:
        st.subheader("3. Document retrieval (PDF pages)")
        if trace.restrict_files:
            st.caption("Scoped to: " + ", ".join(trace.restrict_files))
        hits = [{"citation": h.cite, "score": round(h.score, 2),
                 "section": h.chunk.heading} for h in trace.doc_hits]
        if hits:
            st.dataframe(hits, use_container_width=True, hide_index=True)

    st.subheader("4. Grounded answer")
    if trace.answer:
        if trace.answer.is_ungrounded:
            st.warning("This answer contains content that is **not grounded** in "
                       "the database or documents (general knowledge), shown "
                       "because the fallback option is enabled.")
        # Escape '$' so Streamlit doesn't treat "$x ... $y" as LaTeX math.
        st.markdown(trace.answer.text.replace("$", "\\$"))
        if trace.answer.coverage_gaps:
            with st.expander("Coverage gaps"):
                for g in trace.answer.coverage_gaps:
                    st.write(f"- {g}")

    st.subheader("5. Citation check")
    total = len(trace.valid_citations) + len(trace.invalid_citations)
    if trace.invalid_citations:
        st.error(f"{len(trace.valid_citations)}/{total} citations resolve. "
                 f"Unverified: {trace.invalid_citations}")
    elif total == 0:
        st.info("No citations in this answer (nothing was drawn from the "
                "sources).")
    else:
        st.success(f"All {total} citations resolve to a retrieved row or "
                   f"document page.")


def main() -> None:
    if not _gate():
        return

    from assistant import config, doc_retriever
    from assistant.pipeline import answer

    # On a Streamlit Cloud redeploy the entry script can reload a moment before
    # its imported modules do. Detect that stale window and ask for a refresh
    # instead of crashing with an AttributeError.
    if not hasattr(doc_retriever, "parse_pdf_bytes"):
        st.warning("The app is finishing an update. Please reload the page in a "
                   "minute (or use Manage app → Reboot).")
        st.stop()

    stats = _ensure_data()

    # --- uploaded documents (parsed once per file, kept for the session) -----
    extra_docs = []
    with st.sidebar:
        st.header("Business Knowledge Assistant")
        st.caption(
            "Answers business questions from a SQLite database and PDF "
            "documents. It decides which source each question needs, merges "
            "the results, and cites every statement back to a database row "
            "or a document page."
        )
        st.divider()
        st.write(f"**Model:** {config.MODEL}")
        st.write(f"**Reference date:** {config.REFERENCE_DATE}")
        st.write(f"**Corpus:** {stats['pdfs']} sample PDFs, "
                 f"{stats['page_chunks']} pages")

        st.divider()
        st.subheader("Your documents")
        uploads = st.file_uploader(
            "Upload PDFs to query", type=["pdf"], accept_multiple_files=True,
            help="Your file is parsed and queried with citations like "
                 "[DOC:yourfile.pdf:p2]. It is not stored after the session.",
        )
        store = st.session_state.setdefault("uploaded", {})
        if uploads:
            current = {f"{u.name}:{u.size}" for u in uploads}
            for u in uploads:
                key = f"{u.name}:{u.size}"
                if key not in store:
                    with st.spinner(f"Parsing {u.name}…"):
                        store[key] = doc_retriever.parse_pdf_bytes(
                            u.getvalue(), u.name)
            for key in [k for k in store if k not in current]:
                del store[key]
        for chunks in store.values():
            extra_docs.extend(chunks)
        if extra_docs:
            files = sorted({c.file for c in extra_docs})
            st.success(f"{len(files)} uploaded · {len(extra_docs)} pages "
                       f"indexed: {', '.join(files)}")

        st.divider()
        allow_ungrounded = st.checkbox(
            "Answer from general knowledge if not in sources",
            value=False,
            help="Off (default): the assistant only answers from your data and "
                 "documents, and says when something isn't covered. On: it may "
                 "add a general-knowledge answer, clearly labelled as NOT "
                 "grounded in your sources, with no citations.",
        )

        st.divider()
        st.caption("Try a sample question:")
        for i, q in enumerate(SAMPLE_QUESTIONS):
            label = (q[:48] + "…") if len(q) > 49 else q
            if st.button(label, key=f"sample_{i}", use_container_width=True):
                st.session_state["question"] = q

    st.title("Ask a business question")
    st.caption("English or Hebrew. Questions that need both the database and "
               "the documents are the interesting ones. Upload your own PDFs in "
               "the sidebar to query them.")

    question = st.text_area(
        "Question", value=st.session_state.get("question", ""),
        height=80, label_visibility="collapsed",
        placeholder="e.g. Which customers have overdue payments and what does "
                    "the agreement say about service suspension?",
    )
    run = st.button("Answer", type="primary")

    used = st.session_state.get("used", 0)
    if used >= MAX_QUERIES:
        st.warning(f"Demo limit reached ({MAX_QUERIES} questions this session). "
                   "Refresh to start over.")
        return

    if run and question.strip():
        st.session_state["used"] = used + 1
        try:
            with st.spinner("Routing, retrieving, and grounding the answer..."):
                trace = answer(
                    question.strip(),
                    extra_docs=extra_docs or None,
                    allow_ungrounded=allow_ungrounded,
                )
        except Exception as exc:
            st.error(f"Error: {exc}")
            if "credential" in str(exc).lower():
                st.info("The ANTHROPIC_API_KEY secret is not set on the app.")
            return
        _render(trace)


if __name__ == "__main__":
    main()
