"""Decide which source(s) a question needs (SQL, documents, or both) and pull
out a focused sub-query for the document side."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import db, llm

INTENTS = ["facts", "summary", "analysis", "comparison", "recommendation"]

SYSTEM = f"""You are the query router for a business knowledge assistant. You
make two decisions about each question.

A) INTENT — what kind of answer the question wants:
   - "facts"          a direct lookup (a date, an amount, a status, a list).
   - "summary"        condense / summarize content across one or more sources.
   - "analysis"       interpret or explain implications, not just restate facts.
   - "comparison"     contrast two or more entities, options, or clauses.
   - "recommendation" advise on an action, grounded in the data and documents.

B) SOURCES — where the answer must come from:
   1. "sql"  — a structured SQLite business database. Use it for facts, filters,
      counts, dates, money, statuses, and lists of entities.
   2. "docs" — the text of contract and project PDFs. Use it for what an
      agreement or charter *says*: clauses, penalties, suspension terms, risks.

Database schema:
{db.SCHEMA_DESCRIPTION}

Rules:
- Pick exactly one 'intent' from the list above.
- Choose the minimal set of 'sources' that can fully answer the question. Many
  real questions need BOTH: e.g. "which contracts expire in 90 days and what
  penalties do they define" needs sql (the date filter) and docs (the penalty
  clauses). Prefer both when the question mixes a data filter with a question
  about what a document says.
- For the document side, write 'doc_query': a short, faithful phrase naming the
  exact thing the user asked about in the PDFs (e.g. "penalties", "service
  suspension terms", "project risks"). Use the user's own wording; do NOT add
  adjacent concepts they did not ask about. Leave it empty if docs not needed.
- 'reasoning' is one sentence explaining the decision.
Answer by calling the 'route' tool. Handle English or Hebrew the same way."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": INTENTS,
            "description": "The kind of answer the question wants.",
        },
        "sources": {
            "type": "array",
            "items": {"type": "string", "enum": ["sql", "docs"]},
            "description": "Minimal set of sources required.",
        },
        "doc_query": {
            "type": "string",
            "description": "What to search for in the PDFs; empty if docs not needed.",
        },
        "reasoning": {"type": "string"},
    },
    "required": ["intent", "sources", "doc_query", "reasoning"],
}


@dataclass
class Route:
    intent: str
    sources: list[str]
    doc_query: str
    reasoning: str

    @property
    def needs_sql(self) -> bool:
        return "sql" in self.sources

    @property
    def needs_docs(self) -> bool:
        return "docs" in self.sources


def route(question: str) -> Route:
    out = llm.structured(
        system=SYSTEM,
        user=question,
        tool_name="route",
        tool_description="Record the intent and the sources needed to answer.",
        input_schema=SCHEMA,
        max_tokens=1024,
    )
    sources = [s for s in out.get("sources", []) if s in ("sql", "docs")]
    if not sources:  # never route to nothing
        sources = ["sql", "docs"]
    intent = out.get("intent", "facts")
    if intent not in INTENTS:
        intent = "facts"
    return Route(
        intent=intent,
        sources=sources,
        doc_query=out.get("doc_query", "").strip(),
        reasoning=out.get("reasoning", "").strip(),
    )
