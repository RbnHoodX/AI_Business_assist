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
    """Build the sample DB and PDFs once per container if they are missing."""
    from assistant import config
    from data import build_database, generate_pdfs

    if not config.DB_PATH.exists():
        build_database.build()
    if not any(config.PDF_DIR.glob("*.pdf")):
        generate_pdfs.build()
    from assistant import doc_retriever
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
    "How many active contracts are there and what is their total annual value?",
    "אילו חוזים פגי תוקף ב-90 הימים הקרובים ומהם הקנסות המוגדרים בהם?",
]


def _render(trace) -> None:
    from assistant.synthesizer import CITATION_RE  # noqa: F401

    r = trace.route
    st.subheader("1. Routing decision")
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
    else:
        st.success(f"All {total} citations resolve to a retrieved row or "
                   f"document page.")


def main() -> None:
    if not _gate():
        return

    from assistant import config
    from assistant.pipeline import answer

    stats = _ensure_data()

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
        st.write(f"**Corpus:** {stats['pdfs']} PDFs, "
                 f"{stats['page_chunks']} pages")
        st.caption("All data is sanitized sample data.")
        st.divider()
        st.caption("Try a sample question:")
        for i, q in enumerate(SAMPLE_QUESTIONS):
            label = (q[:48] + "…") if len(q) > 49 else q
            if st.button(label, key=f"sample_{i}", use_container_width=True):
                st.session_state["question"] = q

    st.title("Ask a business question")
    st.caption("English or Hebrew. Questions that need both the database and "
               "the documents are the interesting ones.")

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
                trace = answer(question.strip())
        except Exception as exc:
            st.error(f"Error: {exc}")
            if "credential" in str(exc).lower():
                st.info("The ANTHROPIC_API_KEY secret is not set on the app.")
            return
        _render(trace)


if __name__ == "__main__":
    main()
