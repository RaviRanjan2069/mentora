"""Doubly robust off-policy evaluation with a learner-level bootstrap lower bound.

Per-decision DR (Jiang & Li 2016; Thomas & Brunskill 2016) for a deterministic target
policy pi, using the logged behaviour propensities mu:

    V_DR = sum_t gamma^t [ w_t * r_t - (w_t * Q(s_t, a_t) - w_{t-1} * V(s_t)) ]
    w_t  = prod_{k<=t} min(pi(a_k|s_k) / mu(a_k|s_k), clip),  V(s) = Q(s, pi(s))

Q is fitted by fitted-Q evaluation (ridge regression on [s, onehot(a)]) for the target
policy. Values are reported per episode so they can be bootstrapped by learner and split
by group for the fairness check.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import Ridge

from mentora.reward.dataset_builder import Dataset, Episode, Step

StepPolicy = Callable[[Step], int]


def rule_target(step: Step) -> int:
    """The rule policy's choice at a logged step: the mode of the logged behaviour
    distribution (Collect mode centres its softmax on the rule's choice)."""
    return int(np.argmax(step.behaviour_probs))


def model_target(model: object) -> StepPolicy:
    act = model.act  # type: ignore[attr-defined]
    return lambda step: int(act(step.state, step.feasible, step.graded))


def _features(states: np.ndarray, actions: np.ndarray, n_actions: int) -> np.ndarray:
    onehot = np.zeros((len(actions), n_actions))
    onehot[np.arange(len(actions)), actions] = 1.0
    return np.hstack([states, onehot])


class FQE:
    def __init__(
        self, data: Dataset, pi: StepPolicy, gamma: float, iterations: int, alpha: float
    ) -> None:
        self.n_actions = data.n_actions
        steps = data.steps
        nxt: list[Step | None] = []
        for e in data.episodes:
            nxt.extend([*e.steps[1:], None])
        s = np.stack([x.state for x in steps])
        a = np.asarray([x.action for x in steps])
        r = np.asarray([x.reward for x in steps])
        x = _features(s, a, self.n_actions)
        x2 = np.stack(
            [
                _features(n.state[None, :], np.asarray([pi(n)]), self.n_actions)[0]
                if n is not None
                else np.zeros(x.shape[1])
                for n in nxt
            ]
        )
        done = np.asarray([n is None for n in nxt], dtype=float)
        self.model = Ridge(alpha=alpha)
        y = r.copy()
        for _ in range(iterations):
            self.model.fit(x, y)
            y = r + gamma * (1 - done) * self.model.predict(x2)
        self.model.fit(x, y)

    def q(self, state: np.ndarray, action: int) -> float:
        return float(
            self.model.predict(_features(state[None, :], np.asarray([action]), self.n_actions))[0]
        )


@dataclass(frozen=True)
class OPEResult:
    value: float
    lcb: float
    ucb: float
    n_episodes: int
    effective_sample_size: float  # per decision: (sum w_t)^2 / sum w_t^2 over all steps
    n_steps: int
    per_episode: np.ndarray
    learners: np.ndarray

    def summary(self) -> dict[str, float]:
        return {
            "value": round(self.value, 4),
            "lcb": round(self.lcb, 4),
            "ucb": round(self.ucb, 4),
            "n_episodes": float(self.n_episodes),
            "ess": round(self.effective_sample_size, 1),
            "n_steps": float(self.n_steps),
        }


def dr_episode(
    ep: Episode, pi: StepPolicy, fqe: FQE, gamma: float, clip: float
) -> tuple[float, list[float]]:
    """DR value of one episode, and the cumulative weight w_t at every step."""
    total, w_prev, disc = 0.0, 1.0, 1.0
    ws = []
    for st in ep.steps:
        target = pi(st)
        rho = (1.0 if target == st.action else 0.0) / max(st.propensity, 1e-12)
        w = min(w_prev * rho, clip)
        v_s = fqe.q(st.state, target)
        total += disc * (w * st.reward - (w * fqe.q(st.state, st.action) - w_prev * v_s))
        w_prev, disc = w, disc * gamma
        ws.append(w)
    return total, ws


def evaluate(
    data: Dataset,
    pi: StepPolicy,
    *,
    gamma: float,
    clip: float,
    iterations: int,
    alpha: float,
    bootstrap: int,
    lcb_alpha: float,
    seed: int,
) -> OPEResult:
    fqe = FQE(data, pi, gamma, iterations, alpha)
    vals: list[float] = []
    weights: list[float] = []
    for ep in data.episodes:
        v, ws = dr_episode(ep, pi, fqe, gamma, clip)
        vals.append(v)
        weights.extend(ws)
    per = np.asarray(vals)
    learners = np.asarray([e.learner_id for e in data.episodes])
    w = np.asarray(weights)
    ess = float(w.sum() ** 2 / (w**2).sum()) if (w**2).sum() > 0 else 0.0
    lcb, ucb = bootstrap_bounds(per, learners, bootstrap, lcb_alpha, seed)
    return OPEResult(float(per.mean()), lcb, ucb, len(per), ess, len(w), per, learners)


def bootstrap_bounds(
    per_episode: np.ndarray, learners: np.ndarray, n: int, alpha: float, seed: int
) -> tuple[float, float]:
    """Resample learners (not episodes), so correlated sessions stay together."""
    rng = np.random.default_rng(seed)
    unique = np.unique(learners)
    groups = [per_episode[learners == lr] for lr in unique]
    means = []
    for _ in range(n):
        pick = rng.integers(0, len(groups), size=len(groups))
        means.append(np.concatenate([groups[i] for i in pick]).mean())
    return float(np.quantile(means, alpha)), float(np.quantile(means, 1 - alpha))
