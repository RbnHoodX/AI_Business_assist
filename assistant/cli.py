"""Command-line interface.

Usage:
    python -m assistant.cli "your question"
    python -m assistant.cli            # interactive prompt

Prints the full retrieval flow — routing decision, SQL run, retrieved document
spans, the merged grounded answer, and a citation-verification summary — so the
architecture (not just the answer) is visible.
"""
from __future__ import annotations

import json
import sys
import textwrap

from . import config
from .pipeline import Trace, answer

# --- tiny ANSI helpers (no dependency) ---------------------------------------
def _supports_color() -> bool:
    return sys.stdout.isatty()


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _supports_color() else text


def header(text: str) -> str:
    return c(f"\n{'─' * 78}\n{text}\n{'─' * 78}", "1;36")


def label(text: str) -> str:
    return c(text, "1;33")


def render(trace: Trace) -> None:
    print(header(f"QUESTION"))
    print(trace.question)

    # 1. Routing
    print(header("1. ROUTING DECISION"))
    print(f"{label('sources ')}: {', '.join(trace.route.sources)}")
    if trace.route.doc_query:
        print(f"{label('doc query')}: {trace.route.doc_query}")
    print(f"{label('reasoning')}: {trace.route.reasoning}")

    # 2. SQL
    if trace.sql is not None:
        print(header("2. STRUCTURED RETRIEVAL (SQLite)"))
        print(label("generated SQL:"))
        print(textwrap.indent(trace.sql.sql, "    "))
        print(f"{label('intent')}: {trace.sql.explanation}")
        if trace.sql.error:
            print(c(f"SQL ERROR: {trace.sql.error}", "1;31"))
        else:
            print(label(f"\n{len(trace.sql.rows)} row(s):"))
            for item in trace.sql.cited_rows():
                print(f"  [{c(item['cite'], '32')}] "
                      f"{json.dumps(item['data'], ensure_ascii=False)}")
            if trace.sql.document_files():
                print(label("\nlinked documents (entity match): ")
                      + ", ".join(trace.sql.document_files()))

    # 3. Documents
    if trace.route.needs_docs:
        print(header("3. UNSTRUCTURED RETRIEVAL (PDF spans, BM25)"))
        if trace.restrict_files:
            print(label("scoped to: ") + ", ".join(trace.restrict_files))
        else:
            print(label("scope: ") + "full corpus")
        for h in trace.doc_hits:
            print(f"  [{c(h.cite, '32')}]  score={h.score:5.2f}  "
                  f"{h.chunk.heading}")

    # 4. Answer
    print(header("4. GROUNDED ANSWER"))
    if trace.answer:
        print(trace.answer.text)
        if trace.answer.coverage_gaps:
            print(label("\ncoverage gaps:"))
            for g in trace.answer.coverage_gaps:
                print(f"  • {g}")
        print(label("\ninline citations:"))
        available = trace.available_citation_ids()
        for cid in trace.answer.cited_ids:
            ok = cid in available
            mark = c("✓", "32") if ok else c("✗ UNVERIFIED", "1;31")
            print(f"  {mark} [{cid}]")

    # 5. Verification
    print(header("5. CITATION VERIFICATION"))
    total = len(trace.valid_citations) + len(trace.invalid_citations)
    print(f"{label('resolved to retrieved evidence')}: "
          f"{len(trace.valid_citations)}/{total}")
    if trace.invalid_citations:
        print(c(f"unverified: {trace.invalid_citations}", "1;31"))
    else:
        print(c("all citations resolve to retrieved evidence.", "32"))
    print()


def run_once(question: str) -> None:
    try:
        trace = answer(question)
    except Exception as exc:  # keep the CLI friendly
        print(c(f"\nError: {exc}", "1;31"))
        if "credentials" in str(exc).lower():
            print("Set ANTHROPIC_API_KEY (see .env.example / README).")
        return
    render(trace)


def main() -> None:
    print(c(f"Business Knowledge Assistant  ·  model={config.MODEL}  "
            f"·  reference_date={config.REFERENCE_DATE}", "2"))
    if len(sys.argv) > 1:
        run_once(" ".join(sys.argv[1:]))
        return
    print("Enter a question (blank line to quit).")
    while True:
        try:
            q = input(c("\n? ", "1;36")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            break
        run_once(q)


if __name__ == "__main__":
    main()
