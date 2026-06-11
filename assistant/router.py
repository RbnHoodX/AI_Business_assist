"""Decide which source(s) a question needs (SQL, documents, or both) and pull
out a focused sub-query for the document side."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import db, llm

SYSTEM = f"""You are the query router for a business knowledge assistant.
You decide where an answer must come from. Two retrieval sources exist:

1. "sql"  — a structured SQLite business database. Use it for facts, filters,
   counts, dates, money, statuses, and lists of entities.
2. "docs" — the text of contract and project PDFs. Use it for what an agreement
   or charter *says*: clauses, penalties, suspension terms, risks, obligations.

Database schema:
{db.SCHEMA_DESCRIPTION}

Rules:
- Choose the minimal set of sources that can fully answer the question.
- Many real questions need BOTH: e.g. "which contracts expire in 90 days and
  what penalties do they define" needs sql (the date filter) and docs (the
  penalty clauses). Prefer both when the question mixes a data filter with a
  question about what a document says.
- For the document side, write 'doc_query': a short phrase describing what to
  look for in the PDFs (e.g. "late delivery penalty clause", "service
  suspension terms", "project risks"). Leave it empty if docs are not needed.
- 'reasoning' is one sentence explaining the routing decision.
Answer by calling the 'route' tool. Respond in the same spirit regardless of
the question's language (English or Hebrew)."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
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
    "required": ["sources", "doc_query", "reasoning"],
}


@dataclass
class Route:
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
        tool_description="Record which sources are needed to answer the question.",
        input_schema=SCHEMA,
        max_tokens=1024,
    )
    sources = [s for s in out.get("sources", []) if s in ("sql", "docs")]
    if not sources:  # never route to nothing
        sources = ["sql", "docs"]
    return Route(
        sources=sources,
        doc_query=out.get("doc_query", "").strip(),
        reasoning=out.get("reasoning", "").strip(),
    )
