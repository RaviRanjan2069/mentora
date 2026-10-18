"""Hybrid retrieval: score = beta * minmax(BM25) + (1 - beta) * cosine(embedding)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi

from mentora.db import ASC, StoreFactory
from mentora.db import models as m
from mentora.rag.embeddings import Embedder
from mentora.rag.text import words


@dataclass(frozen=True)
class Passage:
    id: str
    text: str
    section: str | None = None
    week: int | None = None
    concept_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoredPassage:
    passage: Passage
    score: float
    bm25: float = 0.0
    cosine: float = 0.0


def minmax(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values.astype(float)
    lo, hi = float(values.min()), float(values.max())
    if hi - lo < 1e-12:
        return np.zeros_like(values, dtype=float)
    return (values - lo) / (hi - lo)


class HybridRetriever:
    def __init__(
        self,
        passages: Sequence[Passage],
        embeddings: Sequence[Sequence[float]],
        embedder: Embedder,
        *,
        beta: float,
        top_k: int,
    ) -> None:
        if len(passages) != len(embeddings):
            raise ValueError("one embedding per passage")
        self.passages = list(passages)
        self.embedder = embedder
        self.beta = beta
        self.top_k = top_k
        matrix = (
            np.asarray(embeddings, dtype=float).reshape(len(passages), -1)
            if passages
            else np.zeros((0, embedder.dim))
        )
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        self._emb = matrix / np.where(norms == 0, 1.0, norms)
        tokenized = [words(f"{p.section or ''} {p.text}") or ["_"] for p in self.passages]
        self._bm25 = BM25Okapi(tokenized) if self.passages else None

    @classmethod
    def from_db(
        cls,
        session_factory: StoreFactory,
        course_id: int,
        embedder: Embedder,
        *,
        beta: float,
        top_k: int,
    ) -> HybridRetriever:
        with session_factory() as db:
            rows = db.find(m.CorpusPassage, {"course_id": course_id}, sort=[("id", ASC)])
        passages = [Passage(r.id, r.text, r.section, r.week, tuple(r.concept_keys)) for r in rows]
        missing = [i for i, r in enumerate(rows) if r.embedding is None]
        vectors = [r.embedding for r in rows]
        if missing:
            fresh = embedder.embed([f"{rows[i].section or ''}\n{rows[i].text}" for i in missing])
            for i, v in zip(missing, fresh, strict=True):
                vectors[i] = v
        return cls(passages, [v or [] for v in vectors], embedder, beta=beta, top_k=top_k)

    def retrieve(
        self, query: str, *, k: int | None = None, max_week: int | None = None
    ) -> list[ScoredPassage]:
        """Top-k passages; ``max_week`` hides material from later weeks."""
        if not self.passages or self._bm25 is None:
            return []
        idx = np.array(
            [
                i
                for i, p in enumerate(self.passages)
                if max_week is None or p.week is None or p.week <= max_week
            ],
            dtype=int,
        )
        if idx.size == 0:
            return []
        bm25 = np.asarray(self._bm25.get_scores(words(query)), dtype=float)[idx]
        q = np.asarray(self.embedder.embed([query])[0], dtype=float)
        q = q / (np.linalg.norm(q) or 1.0)
        cos = self._emb[idx] @ q
        score = self.beta * minmax(bm25) + (1 - self.beta) * cos
        order = np.argsort(-score, kind="stable")[: k or self.top_k]
        return [
            ScoredPassage(self.passages[idx[j]], float(score[j]), float(bm25[j]), float(cos[j]))
            for j in order
        ]
