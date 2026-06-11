"""Self-test harness.

Offline checks (no API, deterministic, free):
  - SQLite injection / write guard
  - DB build integrity
  - document retrieval EN + HE (same-language)
  - inline-citation regex extraction
  - answer cleanup of leaked scaffolding

Online checks (Claude API):
  - routing correctness per question class (sql-only / docs-only / both)
  - end-to-end pipeline invariants over a question set, repeated N times:
      * answer non-empty, no leaked XML/tool scaffolding
      * every inline citation resolves to retrieved evidence (0 unverified)
      * both-source questions actually cite both DB and DOC

Usage:
  python self_test.py            # offline + online
  python self_test.py --offline  # offline only
"""
from __future__ import annotations

import sys
import traceback

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((PASS if cond else FAIL, name, detail))
    mark = "\033[32m✓\033[0m" if cond else "\033[1;31m✗\033[0m"
    print(f"  {mark} {name}" + (f"  — {detail}" if detail and not cond else ""))


# --------------------------------------------------------------------------- #
# OFFLINE
# --------------------------------------------------------------------------- #
def offline() -> None:
    print("\n=== OFFLINE CHECKS ===")
    from assistant import db, doc_retriever
    from assistant.synthesizer import CITATION_RE, _clean

    # 1. SQL guard rejects writes / multi-statement / non-select.
    print("[SQL guard]")
    bad = [
        "DROP TABLE customers",
        "SELECT 1; DROP TABLE customers",
        "DELETE FROM payments",
        "UPDATE contracts SET annual_value = 0",
        "INSERT INTO customers VALUES ('x','y','z','w')",
        "SELECT * FROM customers; --",
        "PRAGMA table_info(customers)",
        "WITH t AS (SELECT 1) DELETE FROM t",
        "",
    ]
    for q in bad:
        ok, _ = db.is_safe_select(q)
        check(f"rejects: {q[:40]!r}", not ok)
    good = [
        "SELECT * FROM contracts",
        "  select id from projects where status='active'  ",
        "WITH t AS (SELECT id FROM contracts) SELECT * FROM t",
    ]
    for q in good:
        ok, reason = db.is_safe_select(q)
        check(f"allows: {q[:40]!r}", ok, reason)

    # run_select must actually refuse a write even if it slipped through.
    try:
        db.run_select("DELETE FROM customers")
        check("run_select raises on write", False, "did not raise")
    except ValueError:
        check("run_select raises on write", True)

    # run_select returns rows and auto-limits.
    rows = db.run_select("SELECT id FROM contracts")
    check("run_select returns rows", len(rows) == 6, f"got {len(rows)}")

    # 2. DB integrity — every contract/project document_file exists on disk.
    print("[DB integrity / entity links]")
    from assistant import config
    files = {p.name for p in config.PDF_DIR.glob("*.pdf")}
    linked = db.run_select(
        "SELECT document_file FROM contracts UNION "
        "SELECT document_file FROM projects"
    )
    missing = [r["document_file"] for r in linked if r["document_file"] not in files]
    check("all linked PDFs exist", not missing, f"missing={missing}")

    # 3. Document retrieval — English same-language.
    print("[Document retrieval]")
    en = doc_retriever.retrieve("service suspension terms",
                                restrict_files=["contract_C001.pdf"])
    check("EN retrieval finds suspension page",
          any(h.chunk.page == 5 for h in en),
          f"pages={[h.chunk.page for h in en]}")

    # Hebrew same-language.
    he = doc_retriever.retrieve("קנסות והשעיית שירות",
                                restrict_files=["contract_C006.pdf"])
    he_headings = [h.chunk.heading for h in he]
    check("HE retrieval ranks Hebrew penalty/suspension pages",
          any("קנס" in x for x in he_headings) and any("השעי" in x for x in he_headings),
          f"headings={he_headings}")

    # entity scoping really restricts the corpus.
    scoped = doc_retriever.retrieve("penalty", restrict_files=["contract_C002.pdf"])
    check("entity scoping restricts to one file",
          all(h.chunk.file == "contract_C002.pdf" for h in scoped))

    # 4. Citation regex + cleanup.
    print("[Citation extraction / cleanup]")
    sample = ("A [DB:contracts:C001] and B [DOC:contract_C001.pdf:p4] and again "
              "[DB:contracts:C001].")
    found = CITATION_RE.findall(sample)
    check("regex finds all inline citations", len(found) == 3, f"found={found}")
    leaked = "Answer text.</answer>\n<parameter name=\"citations\">[...]"
    check("cleanup strips leaked scaffolding",
          _clean(leaked) == "Answer text.", repr(_clean(leaked)))


# --------------------------------------------------------------------------- #
# ONLINE
# --------------------------------------------------------------------------- #
ROUTING_CASES = [
    # question, expected sources (as a set), label
    ("How many active contracts are there?", {"sql"}, "sql-only"),
    ("What does the Riverstone Master Services Agreement say about termination?",
     {"docs"}, "docs-only (or both)"),
    ("What contracts expire in the next 90 days and what penalties are "
     "defined in those contracts?", {"sql", "docs"}, "both"),
]

PIPELINE_QUESTIONS = [
    "What contracts expire in the next 90 days and what penalties are defined "
    "in those contracts?",
    "Which customers have overdue payments and what does the agreement say "
    "about service suspension?",
    "Show all active projects and summarize the risks mentioned in their "
    "documentation.",
    "אילו חוזים פגי תוקף ב-90 הימים הקרובים ומהם הקנסות המוגדרים בהם?",
]

LEAK_MARKERS = ("</answer>", "<answer>", "<parameter", "function_calls")


def online(rounds: int = 2) -> None:
    print("\n=== ONLINE CHECKS (Claude API) ===")
    from assistant import router
    from assistant.pipeline import answer

    print("[Routing]")
    for q, expected, label in ROUTING_CASES:
        r = router.route(q)
        got = set(r.sources)
        # 'both' must include both; single-source must at least include the
        # expected source (docs-only questions may legitimately add sql).
        ok = expected.issubset(got)
        check(f"route {label}: got {sorted(got)}", ok)

    print(f"[Pipeline invariants × {rounds} round(s)]")
    for rnd in range(1, rounds + 1):
        for q in PIPELINE_QUESTIONS:
            tag = f"r{rnd} · {q[:38]}…"
            try:
                t = answer(q)
            except Exception as exc:
                check(tag, False, f"exception: {exc}")
                continue
            ans = t.answer.text if t.answer else ""
            no_leak = not any(m in ans for m in LEAK_MARKERS)
            verified = not t.invalid_citations and bool(t.answer.cited_ids)
            both = ("sql" in t.route.sources and "docs" in t.route.sources)
            has_db = any(c.startswith("DB:") for c in t.answer.cited_ids)
            has_doc = any(c.startswith("DOC:") for c in t.answer.cited_ids)
            dual_ok = (has_db and has_doc) if both else True
            ok = bool(ans) and no_leak and verified and dual_ok
            detail = (f"leak={not no_leak} unverified={t.invalid_citations} "
                      f"cites={len(t.answer.cited_ids)} dual_ok={dual_ok}")
            check(tag, ok, detail)


def main() -> None:
    offline_only = "--offline" in sys.argv
    try:
        offline()
        if not offline_only:
            online()
    except Exception:
        traceback.print_exc()
        results.append((FAIL, "harness crashed", ""))

    n_fail = sum(1 for r in results if r[0] == FAIL)
    n_pass = sum(1 for r in results if r[0] == PASS)
    print("\n" + "=" * 60)
    print(f"SUMMARY: {n_pass} passed, {n_fail} failed")
    if n_fail:
        print("\nFAILURES:")
        for status, name, detail in results:
            if status == FAIL:
                print(f"  ✗ {name}  {detail}")
    print("=" * 60)
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
