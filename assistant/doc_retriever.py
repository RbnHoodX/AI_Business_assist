"""Retrieval over PDF text.

PDFs are parsed into page-level chunks (each section is on its own page, so a
page number maps to a section). Ranking is BM25, kept dependency-free so the
demo runs offline apart from the Claude API. retrieve() takes a query plus an
optional list of files to restrict to, so swapping in embeddings / a vector DB
later is a local change.

When the SQL step has already narrowed to specific rows, we pass their linked
PDFs as restrict_files and rank within that subset only.

The parsed page text is cached to data/corpus.json. When that file is present
(committed for deployment) the index loads from it, so the runtime needs neither
pdfplumber nor the PDFs in memory. pdfplumber is imported lazily and only used
to build the cache the first time.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from . import config

_TOKEN = re.compile(r"\w+", re.UNICODE)
_ENTITY = re.compile(r"(?:contract|project)_([A-Za-z0-9]+)\.pdf$", re.IGNORECASE)
CORPUS_JSON = config.DATA_DIR / "corpus.json"


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


@dataclass
class Chunk:
    file: str
    page: int          # 1-based
    entity_id: str     # e.g. C001 / P001, parsed from the filename
    heading: str
    text: str
    tokens: list[str]

    @property
    def cite(self) -> str:
        return f"DOC:{self.file}:p{self.page}"


def _parse_pdfs() -> list[dict]:
    """Extract page-level text from every PDF (lazy pdfplumber import)."""
    import pdfplumber  # heavy; only needed when (re)building the cache

    pages: list[dict] = []
    for path in sorted(config.PDF_DIR.glob("*.pdf")):
        m = _ENTITY.search(path.name)
        entity_id = m.group(1).upper() if m else path.stem
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = (page.extract_text() or "").strip()
                if not text:
                    continue
                pages.append({
                    "file": path.name, "page": i, "entity_id": entity_id,
                    "heading": text.split("\n", 1)[0].strip(), "text": text,
                })
    return pages


def build_corpus_cache() -> int:
    """Parse the PDFs and write data/corpus.json. Returns the page count."""
    pages = _parse_pdfs()
    CORPUS_JSON.write_text(json.dumps(pages, ensure_ascii=False, indent=1))
    return len(pages)


def parse_pdf_bytes(data: bytes, filename: str) -> list[Chunk]:
    """Parse an uploaded PDF (raw bytes) into page-level chunks.

    Used by the web app so a user can drop in their own document and query it
    immediately, with citations of the form [DOC:<filename>:p<page>]. No database
    row is required — the chunks join the retrieval pool directly.
    """
    import io
    import pdfplumber

    m = _ENTITY.search(filename)
    entity_id = m.group(1).upper() if m else filename
    chunks: list[Chunk] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            chunks.append(Chunk(
                file=filename, page=i, entity_id=entity_id,
                heading=text.split("\n", 1)[0].strip(),
                text=text, tokens=_tokenize(text),
            ))
    return chunks


@lru_cache(maxsize=1)
def _index() -> list[Chunk]:
    """Load page chunks from the cache, or parse the PDFs if it is missing."""
    if CORPUS_JSON.exists():
        pages = json.loads(CORPUS_JSON.read_text())
    else:
        pages = _parse_pdfs()
    return [
        Chunk(file=p["file"], page=p["page"], entity_id=p["entity_id"],
              heading=p["heading"], text=p["text"], tokens=_tokenize(p["text"]))
        for p in pages
    ]


class _BM25:
    """Minimal BM25 over a fixed chunk set."""

    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.lengths = [len(c.tokens) for c in chunks]
        self.avgdl = (sum(self.lengths) / len(chunks)) if chunks else 0.0
        self.tf: list[dict[str, int]] = []
        df: dict[str, int] = {}
        for c in chunks:
            counts: dict[str, int] = {}
            for tok in c.tokens:
                counts[tok] = counts.get(tok, 0) + 1
            self.tf.append(counts)
            for tok in counts:
                df[tok] = df.get(tok, 0) + 1
        n = len(chunks)
        self.idf = {
            tok: math.log(1 + (n - d + 0.5) / (d + 0.5)) for tok, d in df.items()
        }

    def score(self, query_tokens: list[str], idx: int) -> float:
        counts, dl = self.tf[idx], self.lengths[idx]
        s = 0.0
        for tok in query_tokens:
            f = counts.get(tok, 0)
            if not f:
                continue
            idf = self.idf.get(tok, 0.0)
            denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
            s += idf * (f * (self.k1 + 1)) / denom
        return s


@dataclass
class DocHit:
    chunk: Chunk
    score: float

    @property
    def cite(self) -> str:
        return self.chunk.cite


def retrieve(
    query: str,
    *,
    restrict_files: list[str] | None = None,
    top_k: int | None = None,
    per_file: int = 3,
    extra: list[Chunk] | None = None,
) -> list[DocHit]:
    """Return ranked page chunks for a query.

    `extra` holds chunks from user-uploaded documents; they always join the
    candidate pool so an uploaded file is queryable even though it has no
    database row.

    Two modes:
      - entity-scoped (restrict_files set): the SQL step has already picked the
        relevant documents, so return the top `per_file` pages of EACH document
        (plus any uploaded docs). This guarantees every linked document
        contributes its most relevant sections, and lets a document whose pages
        don't lexically match the query (a Hebrew contract under an English
        query) still surface its pages for the model to read.
      - unscoped: a global BM25 top-k over the corpus plus any uploaded docs.
    """
    extra = list(extra or [])
    top_k = top_k or config.DOC_TOP_K
    if extra:
        top_k = max(top_k, 8)
    corpus = _index()
    if restrict_files:
        sel = [c for c in corpus if c.file in set(restrict_files)]
        scoped = (sel or corpus) + extra
    else:
        scoped = corpus + extra
    if not scoped:
        return []

    bm = _BM25(scoped)
    q = _tokenize(query)
    scored = [(bm.score(q, i), c) for i, c in enumerate(scoped)]

    if restrict_files:
        by_file: dict[str, list[tuple[float, Chunk]]] = {}
        for s, c in scored:
            by_file.setdefault(c.file, []).append((s, c))
        hits: list[DocHit] = []
        for items in by_file.values():
            items.sort(key=lambda x: x[0], reverse=True)
            hits.extend(DocHit(chunk=c, score=s) for s, c in items[:per_file])
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits

    scored.sort(key=lambda x: x[0], reverse=True)
    hits = [DocHit(chunk=c, score=s) for s, c in scored if s > 0][:top_k]
    if not hits:  # query terms missed entirely -> fall back to first pages
        hits = [DocHit(chunk=c, score=0.0) for c in scoped[:top_k]]
    return hits


def corpus_stats() -> dict[str, Any]:
    chunks = _index()
    files = sorted({c.file for c in chunks})
    return {"pdfs": len(files), "page_chunks": len(chunks), "files": files}
