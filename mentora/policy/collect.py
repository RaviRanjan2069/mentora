"""Collect and Deploy modes around any proposer (rule set or learned policy).

* Collect: softmax over F(s) centred on the proposer's choice (temperature T) plus a
  count-based novelty bonus beta / sqrt(N(cluster(s), a) + 1). The sampled action and its
  propensity are logged. This is the only exploration, and it never leaves F(s).
* Deploy: the proposer's choice, propensity 1.
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from mentora.policy.base import Decision, PolicyObs, Proposer
from mentora.policy.catalogue import ESCALATE
from mentora.safety.feasibility import FilterResult


class StateClusters:
    """k-means centroids over logged states; a single cluster until fitted."""

    def __init__(self, centroids: np.ndarray | None = None) -> None:
        self.centroids = centroids

    def assign(self, state: Sequence[float] | np.ndarray) -> int:
        if self.centroids is None or len(self.centroids) == 0:
            return 0
        d = ((self.centroids - np.asarray(state)) ** 2).sum(axis=1)
        return int(d.argmin())

    @classmethod
    def fit(
        cls, states: Sequence[Sequence[float]] | np.ndarray, k: int, seed: int
    ) -> StateClusters:
        from sklearn.cluster import KMeans

        x = np.asarray(states, dtype=float)
        k = max(1, min(k, len(x)))
        km = KMeans(n_clusters=k, random_state=seed, n_init=10).fit(x)
        return cls(km.cluster_centers_)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        cents = [] if self.centroids is None else self.centroids.tolist()
        path.write_text(json.dumps({"centroids": cents}), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> StateClusters:
        if not path.exists():
            return cls()
        cents = json.loads(path.read_text(encoding="utf-8"))["centroids"]
        return cls(np.asarray(cents) if cents else None)


# Explicit learner requests that collect mode answers with the proposer's choice when
# policy.explore_on_requests is false.
HONOURED_REQUESTS = frozenset({"answer", "hint", "example", "practice", "explanation", "question"})


class VisitCounts:
    """N(cluster, action), seeded from logged transitions and updated online."""

    def __init__(self, counts: Counter[tuple[int, str]] | None = None) -> None:
        self.counts: Counter[tuple[int, str]] = counts or Counter()

    def get(self, cluster: int, action_id: str) -> int:
        return self.counts[(cluster, action_id)]

    def add(self, cluster: int, action_id: str) -> None:
        self.counts[(cluster, action_id)] += 1


class BehaviourPolicy:
    def __init__(
        self,
        proposer: Proposer,
        *,
        mode: str,
        temperature: float,
        novelty_beta: float,
        explore_on_requests: bool = True,
        clusters: StateClusters | None = None,
        counts: VisitCounts | None = None,
    ) -> None:
        if mode not in ("collect", "deploy"):
            raise ValueError(f"unknown policy mode {mode!r}")
        self.proposer = proposer
        self.mode = mode
        self.temperature = temperature
        self.novelty_beta = novelty_beta
        self.explore_on_requests = explore_on_requests
        self.clusters = clusters or StateClusters()
        self.counts = counts or VisitCounts()

    @property
    def version(self) -> str:
        return f"{self.proposer.version}/{self.mode}"

    def distribution(self, obs: PolicyObs, allowed: FilterResult) -> tuple[dict[str, float], str]:
        pref = self.proposer.prefer(obs, allowed)
        # Exploration never escalates by chance: ESCALATE gets probability only when it is
        # the proposer's choice (teachers' time is not an exploration budget).
        ids = [
            aid for aid in allowed.feasible_ids() if aid != ESCALATE.id or pref.action == ESCALATE
        ]
        if self.mode == "deploy":
            return {pref.action.id: 1.0}, pref.reason
        if not self.explore_on_requests and obs.request in HONOURED_REQUESTS:
            # The learner asked for something specific: give it. Logged with propensity 1,
            # so off-policy evaluation stays valid (these steps just carry no exploration).
            return {pref.action.id: 1.0}, pref.reason
        cluster = self.clusters.assign(obs.state)
        scores = [
            (1.0 if aid == pref.action.id else 0.0)
            + self.novelty_beta / math.sqrt(self.counts.get(cluster, aid) + 1)
            for aid in ids
        ]
        z = np.asarray(scores) / self.temperature
        z = np.exp(z - z.max())
        p = z / z.sum()
        return {aid: float(pi) for aid, pi in zip(ids, p, strict=True)}, pref.reason

    def decide(self, obs: PolicyObs, allowed: FilterResult, rng: random.Random) -> Decision:
        probs, reason = self.distribution(obs, allowed)
        ids = list(probs)
        if len(ids) == 1:
            chosen = ids[0]
        else:
            chosen = rng.choices(ids, weights=[probs[i] for i in ids], k=1)[0]
        # Renormalise exactly so the logged distribution sums to 1 in floating point.
        total = sum(probs.values())
        probs = {k: v / total for k, v in probs.items()}
        action = next(a for a in allowed.feasible if a.id == chosen)
        if self.mode == "collect":
            self.counts.add(self.clusters.assign(obs.state), chosen)
        return Decision(action, probs[chosen], probs, reason, self.version)
