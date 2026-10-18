"""Study-tactic HMM: fit with Baum-Welch (hmmlearn), choose H by BIC, and keep the
normalised forward posterior alpha_t online with our own filter (no hmmlearn at runtime)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from mentora.learner_model.tactics import TACTICS


@dataclass(frozen=True)
class TacticHMM:
    startprob: np.ndarray  # [H]
    transmat: np.ndarray  # [H, H]
    emissionprob: np.ndarray  # [H, K]

    @property
    def n_states(self) -> int:
        return int(self.startprob.shape[0])

    @classmethod
    def uninformed(cls) -> TacticHMM:
        """One hidden state: alpha is always [1]. Used before any HMM has been fitted."""
        k = len(TACTICS)
        return cls(np.ones(1), np.ones((1, 1)), np.full((1, k), 1 / k))

    def step(self, alpha_prev: np.ndarray | None, obs: int) -> np.ndarray:
        """alpha_t(j) proportional to e_j(o_t) * sum_i alpha_{t-1}(i) A_ij (alpha_0 uses pi)."""
        prior = self.startprob if alpha_prev is None else alpha_prev @ self.transmat
        unnorm = prior * self.emissionprob[:, obs]
        total = unnorm.sum()
        if total <= 0:  # impossible observation under the model: fall back to the prior
            return np.asarray(prior / prior.sum())
        return np.asarray(unnorm / total)

    def filter(self, observations: list[int]) -> np.ndarray:
        out = np.zeros((len(observations), self.n_states))
        alpha = None
        for t, o in enumerate(observations):
            alpha = self.step(alpha, o)
            out[t] = alpha
        return out

    def to_json(self) -> str:
        return json.dumps(
            {
                "startprob": self.startprob.tolist(),
                "transmat": self.transmat.tolist(),
                "emissionprob": self.emissionprob.tolist(),
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> TacticHMM:
        d = json.loads(raw)
        return cls(
            np.asarray(d["startprob"]), np.asarray(d["transmat"]), np.asarray(d["emissionprob"])
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load_or_uninformed(cls, path: Path) -> TacticHMM:
        return (
            cls.from_json(path.read_text(encoding="utf-8")) if path.exists() else cls.uninformed()
        )


def _n_params(h: int, k: int) -> int:
    return (h - 1) + h * (h - 1) + h * (k - 1)


def fit_tactic_hmm(
    sequences: list[list[int]],
    h_min: int,
    h_max: int,
    n_iter: int,
    seed: int,
    restarts: int = 5,
) -> tuple[TacticHMM, dict[int, float]]:
    """Fit an H-state categorical HMM for each H in [h_min, h_max]; keep the lowest BIC.

    Baum-Welch only finds a local optimum, so each H is fitted from ``restarts`` random
    initialisations and the highest-likelihood fit is kept."""
    from hmmlearn.hmm import CategoricalHMM

    seqs = [s for s in sequences if s]
    x = np.concatenate(seqs).reshape(-1, 1)
    lengths = [len(s) for s in seqs]
    k = len(TACTICS)
    bic: dict[int, float] = {}
    best: tuple[float, TacticHMM] | None = None
    for h in range(h_min, h_max + 1):
        fits = []
        for r in range(restarts):
            m = CategoricalHMM(
                n_components=h, n_iter=n_iter, random_state=seed + 1000 * r, n_features=k
            )
            m.fit(x, lengths)
            fits.append((float(m.score(x, lengths)), m))
        log_l, model = max(fits, key=lambda f: f[0])
        bic[h] = -2 * log_l + _n_params(h, k) * np.log(len(x))
        hmm = TacticHMM(model.startprob_, model.transmat_, model.emissionprob_)
        if best is None or bic[h] < best[0]:
            best = (bic[h], hmm)
    assert best is not None
    return best[1], bic
