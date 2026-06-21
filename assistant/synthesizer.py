"""Build the final answer from the retrieved evidence (DB rows + document spans).

Each claim is tagged inline with a citation id:
  - [DB:<table>:<pk>]    a database record
  - [DOC:<file>:p<page>] a document page

The inline citations are what we verify downstream, so we extract them from the
answer text with a regex rather than asking the model for a separate list (which
it doesn't always keep in sync).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import config, llm
from .doc_retriever import DocHit
from .sql_retriever import SqlResult

CITATION_RE = re.compile(r"\[(?:DB|DOC):[^\]]+\]")

SYSTEM = """You are a business knowledge assistant that produces GROUNDED,
cited answers by combining structured database records with document text.

You are given EVIDENCE with two kinds of items, each carrying a citation id:
  - Database rows, id form  [DB:<table>:<pk>]
  - Document spans, id form [DOC:<file>:p<page>]

Strict requirements:
1. Use ONLY the supplied evidence. Never invent facts, numbers, or clauses. If
   the evidence does not cover part of the question, say so explicitly.
2. Every factual sentence must end with one or more citation ids in square
   brackets, copied EXACTLY as given, e.g. "The contract expires 2026-07-15
   [DB:contracts:C001] and defines a $1,000/day late penalty
   [DOC:contract_C001.pdf:p4]."
3. When a fact combines both sources (a record plus what its document says),
   cite both.
4. Answer in the SAME LANGUAGE as the user's question (English or Hebrew).
5. Be concise and business-like. Group by entity where natural.
6. Put the entire response in the 'answer' field. Do not use any XML tags.

Call the 'submit_answer' tool. List any parts of the question the evidence could
not cover in 'coverage_gaps'."""

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "description": "The full answer with inline [DB:..]/[DOC:..] citations.",
        },
        "coverage_gaps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Parts of the question the evidence did not cover.",
        },
    },
    "required": ["answer"],
}


UNGROUNDED_MARKER = "NOT GROUNDED IN YOUR SOURCES"


@dataclass
class Answer:
    text: str
    cited_ids: list[str] = field(default_factory=list)
    coverage_gaps: list[str] = field(default_factory=list)

    @property
    def is_ungrounded(self) -> bool:
        return UNGROUNDED_MARKER in self.text


def _clean(text: str) -> str:
    """Defensively strip any leaked tool/XML scaffolding from the answer."""
    for marker in ("</answer>", "<answer>", "<parameter", "</parameter>"):
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
    return text.strip()


def _evidence_block(sql: SqlResult | None, hits: list[DocHit]) -> str:
    parts: list[str] = []
    if sql and sql.rows:
        parts.append("=== DATABASE ROWS ===")
        for item in sql.cited_rows():
            parts.append(f"[{item['cite']}] {json.dumps(item['data'], ensure_ascii=False)}")
    if hits:
        parts.append("\n=== DOCUMENT SPANS ===")
        for h in hits:
            parts.append(f"[{h.cite}] (heading: {h.chunk.heading})\n{h.chunk.text}")
    if not parts:
        parts.append("(no evidence retrieved)")
    return "\n".join(parts)


# How the answer should be shaped for each question intent. The grounding and
# citation rules are identical; only the form of the answer changes.
INTENT_GUIDANCE = {
    "facts": "The user wants direct facts. Answer concisely, the facts and their "
             "citations, no extra interpretation.",
    "summary": "The user wants a summary. Condense the evidence into the key "
               "points; do not list every raw row.",
    "analysis": "The user wants analysis. State the facts, then explain what they "
                "imply (risk, exposure, timing), strictly within the evidence.",
    "comparison": "The user wants a comparison. Contrast the entities side by "
                  "side on the relevant dimensions; make the differences explicit.",
    "recommendation": "The user wants a recommendation. Give a clear, grounded "
                      "recommendation with its rationale, and note what is "
                      "assumed or missing. Recommend only what the evidence "
                      "supports.",
}


GROUNDED_ONLY = (
    "If the evidence does not contain the answer, say so plainly — state that it "
    "is not available in the provided sources. Do NOT answer from outside or "
    "general knowledge."
)

UNGROUNDED_OK = (
    "If the evidence does not contain the answer, you MAY add an answer from your "
    "own general knowledge, but it MUST be clearly separated and begin with the "
    "exact line '⚠️ NOT GROUNDED IN YOUR SOURCES:'. Do NOT attach any [DB:..] or "
    "[DOC:..] citation to a general-knowledge statement — citations are only for "
    "facts taken from the evidence."
)


def synthesize(
    question: str,
    sql: SqlResult | None,
    hits: list[DocHit],
    intent: str = "facts",
    allow_ungrounded: bool = False,
) -> Answer:
    guidance = INTENT_GUIDANCE.get(intent, INTENT_GUIDANCE["facts"])
    grounding = UNGROUNDED_OK if allow_ungrounded else GROUNDED_ONLY
    user = (
        f"Today's date is {config.REFERENCE_DATE}. Treat any date reasoning "
        f"(e.g. 'next 90 days') as relative to this date; do not hedge about not "
        f"knowing the current date.\n\n"
        f"Question intent: {intent}. {guidance}\n\n"
        f"Grounding policy: {grounding}\n\n"
        f"User question:\n{question}\n\n"
        f"EVIDENCE (cite by the bracketed id):\n{_evidence_block(sql, hits)}"
    )
    out = llm.structured(
        system=SYSTEM,
        user=user,
        tool_name="submit_answer",
        tool_description="Return the grounded answer with inline citations.",
        input_schema=SCHEMA,
        allow_thinking=True,
        max_tokens=4096,
    )
    text = _clean(out.get("answer", ""))
    # Inline citations are the source of truth; extract them in order, de-duped.
    seen: dict[str, None] = {}
    for m in CITATION_RE.findall(text):
        seen.setdefault(m[1:-1], None)  # strip the surrounding brackets
    return Answer(
        text=text,
        cited_ids=list(seen.keys()),
        coverage_gaps=list(out.get("coverage_gaps", []) or []),
    )
