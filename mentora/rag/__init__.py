"""Course-material ingest, hybrid retrieval, reranking, grounding check and audit."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from mentora.config import Settings
from mentora.rag.embeddings import Embedder, make_embedder
from mentora.rag.rerank import RagPipeline, make_reranker
from mentora.rag.retrieve import HybridRetriever


def build_pipeline(
    settings: Settings,
    session_factory: sessionmaker[Session],
    course_id: int,
    embedder: Embedder | None = None,
) -> RagPipeline:
    embedder = embedder or make_embedder(settings)
    retriever = HybridRetriever.from_db(
        session_factory,
        course_id,
        embedder,
        beta=settings.rag.beta,
        top_k=settings.rag.top_k_retrieve,
    )
    return RagPipeline(retriever, make_reranker(settings), settings.rag.top_k_rerank)


__all__ = ["build_pipeline"]
