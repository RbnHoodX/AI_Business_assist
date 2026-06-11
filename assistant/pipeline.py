"""Orchestration: route -> retrieve (sql/docs) -> synthesize -> verify.

Returns a Trace with every intermediate step so the CLI can print the flow. The
final step checks that each citation in the answer matches a row or page that
was actually retrieved.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import doc_retriever, router, sql_retriever, synthesizer
from .doc_retriever import DocHit
from .router import Route
from .sql_retriever import SqlResult
from .synthesizer import Answer


@dataclass
class Trace:
    question: str
    route: Route
    sql: SqlResult | None = None
    doc_hits: list[DocHit] = field(default_factory=list)
    restrict_files: list[str] = field(default_factory=list)
    answer: Answer | None = None
    valid_citations: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)

    def available_citation_ids(self) -> set[str]:
        ids: set[str] = set()
        if self.sql:
            ids.update(item["cite"] for item in self.sql.cited_rows())
        ids.update(h.cite for h in self.doc_hits)
        return ids


def answer(question: str) -> Trace:
    r = router.route(question)
    trace = Trace(question=question, route=r)

    # 1. Structured retrieval.
    if r.needs_sql:
        trace.sql = sql_retriever.retrieve(question)

    # 2. Unstructured retrieval, scoped to the entities the SQL step linked.
    if r.needs_docs:
        restrict = trace.sql.document_files() if trace.sql else []
        trace.restrict_files = restrict
        doc_query = r.doc_query or question
        trace.doc_hits = doc_retriever.retrieve(
            doc_query, restrict_files=restrict or None
        )

    # 3. Grounded synthesis over the merged evidence.
    trace.answer = synthesizer.synthesize(question, trace.sql, trace.doc_hits)

    # 4. Verify inline citations resolve to retrieved evidence (traceability).
    available = trace.available_citation_ids()
    for cid in trace.answer.cited_ids:
        (trace.valid_citations if cid in available
         else trace.invalid_citations).append(cid)

    return trace
