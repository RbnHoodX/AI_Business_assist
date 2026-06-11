"""Structured retrieval: natural language -> SQL -> validated rows.

Each returned row carries a stable citation id of the form [DB:<table>:<pk>] so
the synthesizer can attribute every structured fact back to a specific record.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import config, db, llm

SYSTEM = f"""You translate a business question into ONE read-only SQLite query.

Schema:
{db.SCHEMA_DESCRIPTION}

Hard rules:
- Output exactly one SELECT (or WITH ... SELECT). No INSERT/UPDATE/DELETE/DDL.
- Use the literal current date '{config.REFERENCE_DATE}' wherever "today",
  "now", or relative windows like "next 90 days" are implied.
- ALWAYS include the primary key 'id' of every table you SELECT from, and when a
  row links to a document, include its 'document_file' column too (so the answer
  can pull the matching clauses).
- Prefer returning the identifying columns a human would want to see (names,
  dates, amounts, statuses), not SELECT *.
- 'set_table' must name the single most relevant table the rows come from
  (customers|contracts|payments|projects) — used to build row citations.
Call the 'emit_sql' tool."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sql": {"type": "string", "description": "A single read-only SELECT."},
        "set_table": {
            "type": "string",
            "enum": ["customers", "contracts", "payments", "projects"],
        },
        "explanation": {"type": "string", "description": "One sentence."},
    },
    "required": ["sql", "set_table", "explanation"],
}


@dataclass
class SqlResult:
    sql: str
    table: str
    explanation: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def document_files(self) -> list[str]:
        """Distinct PDFs referenced by the returned rows (entity linking)."""
        files = []
        for r in self.rows:
            f = r.get("document_file")
            if f and f not in files:
                files.append(f)
        return files

    def cited_rows(self) -> list[dict[str, Any]]:
        """Rows annotated with a [DB:table:pk] citation id."""
        out = []
        for r in self.rows:
            # Prefer the row's own pk; fall back to a linked <entity>_id; for
            # aggregate rows (COUNT/SUM) there is no key, so mark it as such.
            pk = r.get("id") or r.get(f"{self.table[:-1]}_id") or "aggregate"
            out.append({"cite": f"DB:{self.table}:{pk}", "data": r})
        return out


def retrieve(question: str) -> SqlResult:
    out = llm.structured(
        system=SYSTEM,
        user=question,
        tool_name="emit_sql",
        tool_description="Emit one read-only SQL query answering the question.",
        input_schema=SCHEMA,
        max_tokens=1500,
    )
    sql = out.get("sql", "").strip()
    table = out.get("set_table", "contracts")
    explanation = out.get("explanation", "").strip()
    result = SqlResult(sql=sql, table=table, explanation=explanation)
    try:
        result.rows = db.run_select(sql)
    except Exception as exc:  # surfaced in the trace rather than crashing
        result.error = str(exc)
    return result
