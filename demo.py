"""Run the three reference questions end-to-end (English + one Hebrew).

    python demo.py

Each question is designed to require BOTH the database and the documents in a
single answer, with row-level and page-level citations.
"""
from __future__ import annotations

from assistant.cli import run_once

QUESTIONS = [
    # Needs: SQL (end_date within 90 days) + DOCS (penalty clauses).
    "What contracts expire in the next 90 days and what penalties are defined "
    "in those contracts?",

    # Needs: SQL (overdue payments + customers) + DOCS (service suspension clauses).
    "Which customers have overdue payments and what does the agreement say "
    "about service suspension?",

    # Needs: SQL (active projects) + DOCS (risk sections).
    "Show all active projects and summarize the risks mentioned in their "
    "documentation.",

    # Intent = comparison: contrast clauses across two named contracts.
    "Compare the penalty terms in the Riverstone and Cobalt contracts.",

    # Intent = recommendation: advise an action, grounded in data + documents.
    "Which customer with an overdue payment should we suspend first, based on "
    "the agreements?",

    # Hebrew: same hybrid flow, answered in Hebrew.
    "אילו חוזים פגי תוקף ב-90 הימים הקרובים ומהם הקנסות המוגדרים בהם?",
]


def main() -> None:
    for q in QUESTIONS:
        run_once(q)


if __name__ == "__main__":
    main()
