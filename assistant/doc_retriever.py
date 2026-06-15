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
) -> list[DocHit]:
    """Return the top BM25-ranked page chunks for a query.

    If restrict_files is non-empty, the search is scoped to those PDFs first
    (entity linking from the SQL step). Falls back to the full corpus if the
    scope is empty.
    """
    top_k = top_k or config.DOC_TOP_K
    chunks = _index()
    if restrict_files:
        scoped = [c for c in chunks if c.file in set(restrict_files)]
        chunks = scoped or chunks
    if not chunks:
        return []

    bm = _BM25(chunks)
    q = _tokenize(query)
    scored = [(bm.score(q, i), c) for i, c in enumerate(chunks)]
    scored.sort(key=lambda x: x[0], reverse=True)

    hits = [DocHit(chunk=c, score=s) for s, c in scored if s > 0][:top_k]
    if not hits:  # query terms missed entirely (e.g. cross-language) -> first pages
        hits = [DocHit(chunk=c, score=0.0) for c in chunks[:top_k]]
    return hits


def corpus_stats() -> dict[str, Any]:
    chunks = _index()
    files = sorted({c.file for c in chunks})
    return {"pdfs": len(files), "page_chunks": len(chunks), "files": files}
