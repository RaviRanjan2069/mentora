"""mastery(learner) -> k in [0, 1]^C.

``CountMastery`` (Beta posterior per concept) works with no training data; ``KTMastery``
queries a trained DKT/AKT-style model (one representative item per concept, since items
are modelled at concept level)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np

from mentora.config.settings import LearnerModelSettings
from mentora.learner_model.kt.data import Interaction


class MasteryModel(Protocol):
    name: str

    def mastery(self, history: list[Interaction], n_concepts: int) -> np.ndarray: ...


class CountMastery:
    name = "count"

    def __init__(self, prior: tuple[float, float]) -> None:
        self.a, self.b = prior

    def mastery(self, history: list[Interaction], n_concepts: int) -> np.ndarray:
        right = np.zeros(n_concepts)
        total = np.zeros(n_concepts)
        for x in history:
            if 0 <= x.concept < n_concepts:
                total[x.concept] += 1
                right[x.concept] += x.correct
        return (right + self.a) / (total + self.a + self.b)


class KTMastery:
    def __init__(self, path: Path) -> None:
        from mentora.learner_model.kt.train import load_model

        self.model = load_model(path)
        self.name = f"kt:{path.stem}"

    def mastery(self, history: list[Interaction], n_concepts: int) -> np.ndarray:
        probs = self.model.mastery(history).numpy().astype(float)
        if probs.shape[0] != n_concepts:
            raise ValueError(f"KT model has {probs.shape[0]} concepts, course has {n_concepts}")
        return np.asarray(probs)


def make_mastery_model(cfg: LearnerModelSettings) -> MasteryModel:
    if cfg.mastery_model != "count":
        path = cfg.model_dir / f"kt_{cfg.mastery_model}.pt"
        if path.exists():
            return KTMastery(path)
    return CountMastery(cfg.count_prior)
