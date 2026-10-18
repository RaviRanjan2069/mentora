"""Second-stage reranking of the hybrid top-20 down to the top-4, and the full pipeline."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Protocol

from mentora.config import Settings
from mentora.rag.retrieve import HybridRetriever, ScoredPassage
from mentora.rag.text import content_words


class Reranker(Protocol):
    def rerank(
        self, query: str, candidates: Sequence[ScoredPassage], top_k: int
    ) -> list[ScoredPassage]: ...


class CrossEncoderReranker:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: Any = None

    def rerank(
        self, query: str, candidates: Sequence[ScoredPassage], top_k: int
    ) -> list[ScoredPassage]:
        if not candidates:
            return []
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name, device="cpu")
        scores = self._model.predict([(query, c.passage.text) for c in candidates])
        ranked = sorted(
            zip(candidates, scores, strict=True), key=lambda cs: float(cs[1]), reverse=True
        )
        return [replace(c, score=float(s)) for c, s in ranked[:top_k]]


class LexicalReranker:
    """Offline stand-in: share of query content words in the passage, ties by hybrid score."""

    def rerank(
        self, query: str, candidates: Sequence[ScoredPassage], top_k: int
    ) -> list[ScoredPassage]:
        q = set(content_words(query))

        def overlap(c: ScoredPassage) -> float:
            if not q:
                return 0.0
            text = set(content_words(f"{c.passage.section or ''} {c.passage.text}"))
            return len(q & text) / len(q)

        ranked = sorted(candidates, key=lambda c: (overlap(c), c.score), reverse=True)
        return [replace(c, score=overlap(c)) for c in ranked[:top_k]]


def make_reranker(settings: Settings) -> Reranker:
    if settings.rag.reranker == "lexical":
        return LexicalReranker()
    return CrossEncoderReranker(settings.rag.reranker_model)


class RagPipeline:
    """Hybrid top-``top_k_retrieve`` -> rerank -> top-``top_k_rerank``."""

    def __init__(self, retriever: HybridRetriever, reranker: Reranker, top_k: int) -> None:
        self.retriever = retriever
        self.reranker = reranker
        self.top_k = top_k

    def search(self, query: str, *, max_week: int | None = None) -> list[ScoredPassage]:
        candidates = self.retriever.retrieve(query, max_week=max_week)
        return self.reranker.rerank(query, candidates, self.top_k)
