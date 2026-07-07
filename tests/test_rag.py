"""Tests for the RAG retrieval layer (scripts/rag.py).

These run offline and deterministically by forcing the HashingEmbedder, so they
never download a model or touch the network. The dense fastembed backend is
exercised separately at runtime, not in CI.

All fixtures use fictional companies and achievements — no personal data.
"""
import numpy as np
import pytest

import scripts.rag as rag


# ── fixtures (synthetic) ──────────────────────────────────────────────────────
ROBOTICS_DOC = """\
---
type: job
company: "Acme Robotics"
---

# Firmware Lead — Acme Robotics

## 30-second summary
Own firmware integration for warehouse robotics and conveyor control systems.

## Key achievements (resume-ready bullets)
- Designed a conveyor scheduling service that cut assembly line bottlenecks by 30 percent
- Built a sensor calibration pipeline for robotic arms across three factory sites

## Notes (internal, not for resume)
- Do not mention the unreleased gripper prototype
"""

BILLING_DOC = """\
---
type: job
company: "Globex Billing"
---

# Platform Analyst — Globex Billing

## Key achievements (resume-ready bullets)
- Built a recurring subscription billing engine handling invoices, proration, and refunds
- Integrated a fraud scoring vendor that reduced payment chargebacks by 25 percent
"""


@pytest.fixture()
def docs_dir(tmp_path):
    (tmp_path / "robotics.md").write_text(ROBOTICS_DOC, encoding="utf-8")
    (tmp_path / "billing.md").write_text(BILLING_DOC, encoding="utf-8")
    return tmp_path


# ── chunking ──────────────────────────────────────────────────────────────────
def test_chunk_document_splits_bullets_and_labels_company():
    chunks = rag.chunk_document(ROBOTICS_DOC, "robotics.md")
    texts = [c.text for c in chunks]
    assert any("conveyor scheduling" in t for t in texts)
    assert any("sensor calibration" in t for t in texts)
    assert all(c.company == "Acme Robotics" for c in chunks)
    # the 30-second summary prose is captured as its own chunk
    assert any("firmware integration" in t for t in texts)


def test_chunk_document_skips_internal_notes():
    chunks = rag.chunk_document(ROBOTICS_DOC, "robotics.md")
    assert not any("gripper prototype" in c.text for c in chunks)
    assert not any("Notes" in c.section for c in chunks)


def test_embed_text_includes_context_label():
    chunks = rag.chunk_document(ROBOTICS_DOC, "robotics.md")
    conveyor = next(c for c in chunks if "conveyor scheduling" in c.text)
    assert "Acme Robotics" in conveyor.embed_text
    assert "Key achievements" in conveyor.embed_text


def test_build_corpus_reads_multiple_files(docs_dir):
    chunks = rag.build_corpus(docs_dir, ["robotics.md", "billing.md"])
    companies = {c.company for c in chunks}
    assert companies == {"Acme Robotics", "Globex Billing"}


def test_build_corpus_ignores_missing_files(docs_dir):
    chunks = rag.build_corpus(docs_dir, ["robotics.md", "does-not-exist.md"])
    assert chunks and all(c.source == "robotics.md" for c in chunks)


# ── embedder ──────────────────────────────────────────────────────────────────
def test_hashing_embedder_deterministic_and_normalized():
    emb = rag.HashingEmbedder()
    a = emb.embed(["subscription billing invoices and refunds"])
    b = emb.embed(["subscription billing invoices and refunds"])
    assert np.allclose(a, b)                      # deterministic
    assert a.shape == (1, rag.HASH_DIM)
    assert np.isclose(np.linalg.norm(a[0]), 1.0)  # unit length


def test_hashing_embedder_empty_input():
    out = rag.HashingEmbedder().embed([])
    assert out.shape == (0, rag.HASH_DIM)


# ── retrieval ─────────────────────────────────────────────────────────────────
def test_retrieve_ranks_relevant_chunk_first(docs_dir):
    index = rag.RagIndex.build(
        rag.build_corpus(docs_dir, ["robotics.md", "billing.md"]),
        rag.HashingEmbedder(),
    )
    hits = index.retrieve("subscription billing invoices proration refunds", k=3)
    top_text = hits[0][0].text.lower()
    assert "billing" in top_text
    assert hits[0][1] >= hits[-1][1]  # scores are sorted descending


def test_retrieve_robotics_query_surfaces_conveyor(docs_dir):
    index = rag.RagIndex.build(
        rag.build_corpus(docs_dir, ["robotics.md", "billing.md"]),
        rag.HashingEmbedder(),
    )
    hits = index.retrieve("conveyor assembly line scheduling robotics", k=2)
    assert any("conveyor scheduling" in c.text for c, _ in hits)


def test_retrieve_empty_index_returns_empty():
    index = rag.RagIndex([], np.zeros((0, rag.HASH_DIM)), rag.HashingEmbedder())
    assert index.retrieve("anything", k=5) == []


def test_retrieve_k_larger_than_corpus(docs_dir):
    chunks = rag.build_corpus(docs_dir, ["robotics.md"])
    index = rag.RagIndex.build(chunks, rag.HashingEmbedder())
    hits = index.retrieve("firmware", k=100)
    assert len(hits) == len(chunks)


# ── caching / staleness ───────────────────────────────────────────────────────
def test_index_cache_roundtrip_and_reload(docs_dir, tmp_path):
    cache = tmp_path / "cache" / "index.npz"
    emb = rag.HashingEmbedder()
    files = ["robotics.md", "billing.md"]

    first = rag.build_or_load(docs_dir, files, embedder=emb, cache_path=cache)
    assert cache.exists()
    top_first = first.retrieve("billing refunds", k=1)[0][0].text

    # second call loads from cache and returns identical top result
    second = rag.build_or_load(docs_dir, files, embedder=emb, cache_path=cache)
    top_second = second.retrieve("billing refunds", k=1)[0][0].text
    assert top_first == top_second


def test_index_rebuilds_when_corpus_changes(docs_dir, tmp_path):
    cache = tmp_path / "cache" / "index.npz"
    emb = rag.HashingEmbedder()
    files = ["robotics.md", "billing.md"]

    rag.build_or_load(docs_dir, files, embedder=emb, cache_path=cache)
    h1 = rag._corpus_hash(rag.build_corpus(docs_dir, files), emb.name)

    (docs_dir / "billing.md").write_text(
        BILLING_DOC + "\n- Added a quantum ledger reconciliation module\n",
        encoding="utf-8",
    )
    h2 = rag._corpus_hash(rag.build_corpus(docs_dir, files), emb.name)
    assert h1 != h2  # staleness key changes when any doc changes

    rebuilt = rag.build_or_load(docs_dir, files, embedder=emb, cache_path=cache)
    assert any("quantum ledger" in c.text for c in rebuilt.chunks)


def test_get_index_is_cached(monkeypatch, docs_dir, tmp_path):
    monkeypatch.setattr(rag, "_INDEX_CACHE", {})
    calls = {"n": 0}
    real = rag.build_or_load

    def counting(d, f, **k):
        calls["n"] += 1
        return real(d, f, embedder=rag.HashingEmbedder(),
                    cache_path=tmp_path / "idx.npz")

    monkeypatch.setattr(rag, "build_or_load", counting)
    rag.get_index(docs_dir, ["robotics.md"])
    rag.get_index(docs_dir, ["robotics.md"])
    assert calls["n"] == 1  # second call served from the in-process cache
