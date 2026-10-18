"""Text embedders. ``SentenceTransformerEmbedder`` is the real one; ``HashingEmbedder`` is a
deterministic offline stand-in for tests (no model download)."""

from __future__ import annotations

import hashlib
import itertools
import math
from collections.abc import Sequence
from typing import Any, Protocol

from mentora.config import Settings
from mentora.rag.text import words


class Embedder(Protocol):
    dim: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Signed feature hashing of unigrams and bigrams, L2-normalised."""

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        toks = words(text)
        feats = toks + [f"{a}_{b}" for a, b in itertools.pairwise(toks)]
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
            vec[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, dim: int) -> None:
        self.model_name = model_name
        self.dim = dim
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device="cpu")
            actual = self._model.get_embedding_dimension()
            if actual != self.dim:
                raise ValueError(f"{self.model_name} gives {actual} dims; config says {self.dim}")
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._load().encode(list(texts), normalize_embeddings=True, batch_size=32)
        return [[float(x) for x in v] for v in vectors]


def make_embedder(settings: Settings) -> Embedder:
    if settings.rag.embedder == "hashing":
        return HashingEmbedder(settings.rag.embedding_dim)
    return SentenceTransformerEmbedder(settings.rag.embedding_model, settings.rag.embedding_dim)
