"""rag.py — Retrieval-Augmented Generation over the career corpus.

The document generator used to stuff the *entire* work history into the prompt
and let the model decide what mattered (context-stuffing). This module makes it
real RAG: the career docs are chunked into individual achievements, embedded once
into a vector index, and the top-k most semantically relevant chunks for a given
job posting are retrieved and injected as prioritized context.

Two phases:
  1. Index (once, cached): chunk docs -> embed each chunk -> persist the matrix.
  2. Retrieve (per posting): embed the JD -> cosine-rank chunks -> return top-k.

Embedding backend:
  - Default: fastembed (BAAI/bge-small-en-v1.5), dense semantic embeddings.
  - Fallback: a deterministic hashing bag-of-words embedder (numpy only), so the
    feature degrades gracefully with no ML deps and tests run offline and fast.

The index is small (a few hundred chunks), so retrieval is exact brute-force
cosine similarity over a normalized matrix — correct and instant at this scale.
Swap in FAISS/pgvector only when the corpus outgrows memory.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

# ── DEFAULTS ──────────────────────────────────────────────────────────────────
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
HASH_DIM = 512
_CACHE_DIR = Path(__file__).parent.parent / ".rag_cache"

# Section headers we never want to retrieve from (internal notes, guardrails).
_SKIP_SECTION = re.compile(r"note|guardrail|internal|keywords?\s*\(ats", re.I)
_BULLET = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")
_HEADER = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_TOKEN = re.compile(r"[a-z0-9]+")


# ── CHUNKING ──────────────────────────────────────────────────────────────────
@dataclass
class Chunk:
    text: str        # the raw achievement / passage
    source: str      # filename it came from
    company: str     # human label for the role/source
    section: str     # the section header it lived under

    @property
    def label(self) -> str:
        return f"{self.company} — {self.section}" if self.section else self.company

    @property
    def embed_text(self) -> str:
        # Give the embedder the surrounding context, not just the bare bullet, so
        # a stray "reduced by over 50%" still carries its company and topic.
        return f"{self.label}: {self.text}"


def _parse_frontmatter_company(raw: str, fallback: str) -> str:
    """Pull a human company/role label out of YAML frontmatter or the H1."""
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            fm = raw[3:end]
            m = re.search(r'^\s*company\s*:\s*"?([^"\n]+)"?\s*$', fm, re.M)
            if m:
                return m.group(1).strip()
    m = re.search(r"^#\s+(.+)$", raw, re.M)
    return m.group(1).strip() if m else fallback


def _strip_frontmatter(raw: str) -> str:
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            return raw[end + 4:]
    return raw


def chunk_document(raw: str, source: str, min_len: int = 15) -> List[Chunk]:
    """Split one markdown doc into retrievable chunks.

    Each bullet becomes its own chunk; contiguous prose under a header is grouped
    into a paragraph chunk. Internal-note / guardrail / ATS-keyword sections are
    skipped so we never retrieve instructions-to-self as if they were experience.
    """
    company = _parse_frontmatter_company(raw, fallback=source)
    body = _strip_frontmatter(raw)
    chunks: List[Chunk] = []
    section = ""
    skip = False
    para: List[str] = []

    def flush_para():
        if para:
            text = " ".join(para).strip()
            if len(text) >= min_len and not skip:
                chunks.append(Chunk(text, source, company, section))
            para.clear()

    for line in body.splitlines():
        h = _HEADER.match(line)
        if h:
            flush_para()
            section = h.group(2).strip()
            skip = bool(_SKIP_SECTION.search(section))
            continue
        b = _BULLET.match(line)
        if b:
            flush_para()
            text = b.group(1).strip()
            if len(text) >= min_len and not skip:
                chunks.append(Chunk(text, source, company, section))
            continue
        if line.strip() == "":
            flush_para()
        else:
            para.append(line.strip())
    flush_para()
    return chunks


def build_corpus(docs_dir: Path, filenames: Sequence[str]) -> List[Chunk]:
    chunks: List[Chunk] = []
    for name in filenames:
        p = Path(docs_dir) / name
        if p.exists():
            chunks.extend(chunk_document(p.read_text(encoding="utf-8"), name))
    return chunks


def _corpus_hash(chunks: Sequence[Chunk], embedder_name: str) -> str:
    h = hashlib.sha256()
    h.update(embedder_name.encode())
    for c in chunks:
        h.update(c.embed_text.encode())
        h.update(b"\x00")
    return h.hexdigest()


# ── EMBEDDERS ─────────────────────────────────────────────────────────────────
def _l2_normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


class HashingEmbedder:
    """Deterministic hashing bag-of-words embedder (numpy only).

    Not semantic — it matches on token overlap — but it needs no model download,
    is fully deterministic, and keeps retrieval (and the tests) working when
    fastembed is unavailable. The real runtime uses the dense backend below.
    """

    name = f"hashing-{HASH_DIM}"

    def __init__(self, dim: int = HASH_DIM):
        self.dim = dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in _TOKEN.findall(text.lower()):
            idx = int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dim
            v[idx] += 1.0
        # sublinear term-frequency dampening
        np.log1p(v, out=v)
        return v

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _l2_normalize(np.vstack([self._vec(t) for t in texts]))


class FastEmbedEmbedder:
    """Dense semantic embeddings via fastembed (ONNX, no torch)."""

    def __init__(self, model: str = DEFAULT_MODEL):
        from fastembed import TextEmbedding  # lazy: heavy import + model download
        self.name = f"fastembed-{model}"
        self._model = TextEmbedding(model_name=model)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        vecs = np.array(list(self._model.embed(list(texts))), dtype=np.float32)
        return _l2_normalize(vecs)


def get_embedder(prefer_dense: bool = True):
    """Return the best available embedder, falling back to hashing."""
    if prefer_dense:
        try:
            return FastEmbedEmbedder()
        except Exception:
            pass
    return HashingEmbedder()


# ── INDEX ─────────────────────────────────────────────────────────────────────
class RagIndex:
    def __init__(self, chunks: List[Chunk], matrix: np.ndarray, embedder):
        self.chunks = chunks
        self.matrix = matrix
        self.embedder = embedder

    @classmethod
    def build(cls, chunks: List[Chunk], embedder) -> "RagIndex":
        matrix = embedder.embed([c.embed_text for c in chunks])
        return cls(chunks, matrix, embedder)

    def retrieve(self, query: str, k: int = 15) -> List[Tuple[Chunk, float]]:
        if not self.chunks or self.matrix.size == 0:
            return []
        q = self.embedder.embed([query])[0]
        scores = self.matrix @ q  # cosine sim: both sides L2-normalized
        k = min(k, len(self.chunks))
        top = np.argsort(-scores)[:k]
        return [(self.chunks[i], float(scores[i])) for i in top]

    def save(self, path: Path, corpus_hash: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            path,
            matrix=self.matrix,
            chunks=json.dumps([asdict(c) for c in self.chunks]),
            meta=json.dumps({"hash": corpus_hash, "embedder": self.embedder.name}),
        )

    @classmethod
    def load(cls, path: Path, embedder) -> Optional["RagIndex"]:
        if not path.exists():
            return None
        try:
            data = np.load(path, allow_pickle=False)
            chunks = [Chunk(**d) for d in json.loads(str(data["chunks"]))]
            return cls(chunks, data["matrix"], embedder)
        except Exception:
            return None


def build_or_load(
    docs_dir: Path,
    filenames: Sequence[str],
    embedder=None,
    cache_path: Optional[Path] = None,
) -> RagIndex:
    """Load a cached index if the corpus and embedder are unchanged, else rebuild.

    Staleness is keyed on a hash of every chunk's text plus the embedder name, so
    editing any docs/ file or switching backends transparently triggers a rebuild.
    """
    embedder = embedder or get_embedder()
    cache_path = cache_path or (_CACHE_DIR / "index.npz")
    chunks = build_corpus(docs_dir, filenames)
    want = _corpus_hash(chunks, embedder.name)

    if cache_path.exists():
        try:
            meta = json.loads(str(np.load(cache_path, allow_pickle=False)["meta"]))
            if meta.get("hash") == want:
                cached = RagIndex.load(cache_path, embedder)
                if cached is not None:
                    return cached
        except Exception:
            pass

    index = RagIndex.build(chunks, embedder)
    try:
        index.save(cache_path, want)
    except Exception:
        pass  # caching is best-effort; never block generation on disk
    return index


# In-process cache so repeated generations in one server reuse the index.
_INDEX_CACHE: dict = {}


def get_index(docs_dir: Path, filenames: Sequence[str]) -> RagIndex:
    key = (str(docs_dir), tuple(filenames))
    if key not in _INDEX_CACHE:
        _INDEX_CACHE[key] = build_or_load(docs_dir, filenames)
    return _INDEX_CACHE[key]


def retrieve_relevant(
    docs_dir: Path,
    filenames: Sequence[str],
    query: str,
    k: int = 18,
) -> List[Tuple[Chunk, float]]:
    """High-level entry point used by the generator."""
    return get_index(docs_dir, filenames).retrieve(query, k)
