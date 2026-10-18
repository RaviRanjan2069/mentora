from __future__ import annotations

import numpy as np
from sqlalchemy.orm import Session, sessionmaker

from mentora.rag.embeddings import HashingEmbedder
from mentora.rag.ingest import PassageDraft
from mentora.rag.rerank import LexicalReranker, RagPipeline
from mentora.rag.retrieve import HybridRetriever, Passage, minmax


def _retriever(
    passages: list[PassageDraft], embedder: HashingEmbedder, beta: float = 0.4
) -> HybridRetriever:
    return HybridRetriever(
        [Passage(p.id, p.text, p.section, p.week, p.concept_keys) for p in passages],
        [list(p.embedding or ()) for p in passages],
        embedder,
        beta=beta,
        top_k=20,
    )


def test_minmax() -> None:
    assert minmax(np.array([2.0, 4.0, 6.0])).tolist() == [0.0, 0.5, 1.0]
    assert minmax(np.array([3.0, 3.0])).tolist() == [0.0, 0.0]


def test_hybrid_finds_relevant_section(
    passages: list[PassageDraft], embedder: HashingEmbedder
) -> None:
    hits = _retriever(passages, embedder).retrieve("what does the range function produce")
    assert len(hits) <= 20
    assert hits[0].passage.section in {"For loops and ranges", "FAQ"}
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_beta_extremes_select_pure_signals(
    passages: list[PassageDraft], embedder: HashingEmbedder
) -> None:
    q = "floor division operator"
    bm25_only = _retriever(passages, embedder, beta=1.0).retrieve(q)
    assert bm25_only[0].bm25 == max(h.bm25 for h in bm25_only)
    cos_only = _retriever(passages, embedder, beta=0.0).retrieve(q)
    assert cos_only[0].cosine == max(h.cosine for h in cos_only)


def test_max_week_hides_later_material(
    passages: list[PassageDraft], embedder: HashingEmbedder
) -> None:
    hits = _retriever(passages, embedder).retrieve("while loop runs forever", max_week=2)
    assert hits and all(h.passage.week is None or h.passage.week <= 2 for h in hits)


def test_pipeline_reranks_to_top4(
    session_factory: sessionmaker[Session], ingested: int, embedder: HashingEmbedder
) -> None:
    retriever = HybridRetriever.from_db(session_factory, ingested, embedder, beta=0.4, top_k=20)
    pipeline = RagPipeline(retriever, LexicalReranker(), top_k=4)
    hits = pipeline.search("Does range(10) include 10?")
    assert len(hits) == 4
    assert any("range" in h.passage.text for h in hits[:2])


def test_empty_index() -> None:
    r = HybridRetriever([], [], HashingEmbedder(384), beta=0.4, top_k=20)
    assert r.retrieve("anything") == []
