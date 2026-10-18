"""Offline policies: the tabular baseline and the ensemble-CQL policy, plus the
target-policy interface used by OPE.

Both learned policies only ever choose inside F(s) (the logged feasible mask offline, the
live filter result online), and both can act as a ``Proposer`` for the live orchestrator.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import torch
from torch import nn

from mentora.config.settings import OfflineSettings, PolicySettings
from mentora.policy.base import PolicyObs, Preference
from mentora.policy.catalogue import ESCALATE, Catalogue
from mentora.policy.collect import StateClusters
from mentora.reward.dataset_builder import Dataset
from mentora.safety.feasibility import FilterResult


class TargetPolicy(Protocol):
    """A deterministic policy evaluated on logged states."""

    def act(self, state: np.ndarray, feasible: np.ndarray, graded: bool) -> int: ...


def _masked_argmax(values: np.ndarray, feasible: np.ndarray) -> int:
    v = np.where(feasible, values, -np.inf)
    return int(np.argmax(v))


# --- tabular baseline -------------------------------------------------------------------------


class TabularQ:
    """ELA-Tutor-style incremental sample-average Q over k-means state clusters:
    Q(c,a) <- Q(c,a) + (r + gamma * max_{a' in F(s')} Q(c',a') - Q(c,a)) / N(c,a)."""

    def __init__(self, clusters: StateClusters, n_actions: int, min_visits: int) -> None:
        self.clusters = clusters
        assert clusters.centroids is not None
        k = len(clusters.centroids)
        self.q = np.zeros((k, n_actions))
        self.n = np.zeros((k, n_actions), dtype=int)
        self.min_visits = min_visits

    @classmethod
    def fit(
        cls, data: Dataset, pcfg: PolicySettings, ocfg: OfflineSettings, epochs: int = 20
    ) -> TabularQ:
        arr = data.arrays()
        clusters = StateClusters.fit(arr["s"], pcfg.n_state_clusters, pcfg.seed)
        model = cls(clusters, data.n_actions, ocfg.tabular_min_visits)
        c = np.asarray([clusters.assign(s) for s in arr["s"]])
        c2 = np.asarray([clusters.assign(s) for s in arr["s2"]])
        for _ in range(epochs):
            visits = np.zeros_like(model.n)
            for i in range(len(c)):
                ci, ai = c[i], arr["a"][i]
                nxt = (
                    0.0
                    if arr["done"][i]
                    else float(np.max(np.where(arr["f2"][i], model.q[c2[i]], -np.inf)))
                )
                nxt = 0.0 if not np.isfinite(nxt) else nxt
                visits[ci, ai] += 1
                target = arr["r"][i] + pcfg.gamma * nxt
                model.q[ci, ai] += (target - model.q[ci, ai]) / visits[ci, ai]
            model.n = visits
        return model

    def values(self, state: np.ndarray) -> np.ndarray:
        return np.asarray(self.q[self.clusters.assign(state)])

    def act(self, state: np.ndarray, feasible: np.ndarray, graded: bool) -> int:
        c = self.clusters.assign(state)
        trusted = feasible & (self.n[c] >= self.min_visits)
        mask = trusted if trusted.any() else feasible
        return _masked_argmax(self.q[c], mask)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        assert self.clusters.centroids is not None
        path.write_text(
            json.dumps(
                {
                    "centroids": self.clusters.centroids.tolist(),
                    "q": self.q.tolist(),
                    "n": self.n.tolist(),
                    "min_visits": self.min_visits,
                }
            )
        )

    @classmethod
    def load(cls, path: Path) -> TabularQ:
        d = json.loads(path.read_text())
        model = cls(StateClusters(np.asarray(d["centroids"])), len(d["q"][0]), d["min_visits"])
        model.q, model.n = np.asarray(d["q"]), np.asarray(d["n"])
        return model


# --- ensemble CQL -----------------------------------------------------------------------------


def _mlp(state_dim: int, hidden: int, n_actions: int) -> nn.Module:
    return nn.Sequential(
        nn.Linear(state_dim, hidden),
        nn.ReLU(),
        nn.Linear(hidden, hidden),
        nn.ReLU(),
        nn.Linear(hidden, n_actions),
    )


class CQLEnsemble:
    """M two-layer MLP Q-networks, each trained on a learner-level bootstrap resample
    with the discrete CQL loss restricted to F(s). Decision: argmax over F(s) of
    mean_Q - kappa * std_Q; ESCALATE if the chosen action's std exceeds tau_u on a
    high-stakes (graded) step."""

    def __init__(
        self,
        nets: list[nn.Module],
        kappa: float,
        tau_u: float | None,
        escalate_index: int,
        meta: dict[str, Any],
    ) -> None:
        self.nets = nets
        self.kappa = kappa
        self.tau_u = tau_u
        self.escalate_index = escalate_index
        self.meta = meta

    @staticmethod
    def _train_one(
        arr: dict[str, np.ndarray],
        idx: np.ndarray,
        n_actions: int,
        gamma: float,
        cfg: OfflineSettings,
        seed: int,
    ) -> nn.Module:
        torch.manual_seed(seed)
        rng = np.random.default_rng(seed)
        dim = arr["s"].shape[1]
        net, target = _mlp(dim, cfg.hidden, n_actions), _mlp(dim, cfg.hidden, n_actions)
        target.load_state_dict(net.state_dict())
        opt = torch.optim.Adam(net.parameters(), lr=cfg.lr)
        t = {k: torch.as_tensor(v[idx]) for k, v in arr.items()}
        s, s2 = t["s"].float(), t["s2"].float()
        a, r, done = t["a"].long(), t["r"].float(), t["done"].float()
        f, f2 = t["f"].bool(), t["f2"].bool()
        neg = torch.tensor(-1e9)
        for _ in range(cfg.epochs):
            order = rng.permutation(len(idx))
            for i in range(0, len(idx), cfg.batch_size):
                b = torch.as_tensor(order[i : i + cfg.batch_size])
                q = net(s[b])
                q_sa = q.gather(1, a[b].unsqueeze(1)).squeeze(1)
                with torch.no_grad():
                    q2 = torch.where(f2[b], target(s2[b]), neg).max(dim=1).values
                    y = r[b] + gamma * (1 - done[b]) * q2
                td = nn.functional.mse_loss(q_sa, y)
                # Conservative penalty: push down Q on all feasible actions, up on logged ones.
                lse = torch.logsumexp(torch.where(f[b], q, neg), dim=1)
                loss = td + cfg.cql_alpha * (lse - q_sa).mean()
                opt.zero_grad()
                loss.backward()
                opt.step()
                with torch.no_grad():
                    for p, tp in zip(net.parameters(), target.parameters(), strict=True):
                        tp.mul_(1 - cfg.target_tau).add_(cfg.target_tau * p)
        net.eval()
        return net

    @classmethod
    def fit(
        cls,
        train: Dataset,
        val: Dataset,
        catalogue: Catalogue,
        pcfg: PolicySettings,
        ocfg: OfflineSettings,
    ) -> CQLEnsemble:
        arr = train.arrays()
        steps = train.steps
        learners = np.asarray([s.learner_id for s in steps])
        unique = np.unique(learners)
        rng = np.random.default_rng(pcfg.seed)
        nets = []
        for k in range(pcfg.ensemble_m):
            boot = rng.choice(unique, size=len(unique), replace=True)  # bootstrap by learner
            idx = np.concatenate([np.flatnonzero(learners == lr) for lr in boot])
            nets.append(
                cls._train_one(arr, idx, train.n_actions, pcfg.gamma, ocfg, pcfg.seed * 1000 + k)
            )
        esc = train.action_ids.index(ESCALATE.id)
        model = cls(
            nets,
            pcfg.kappa,
            None,
            esc,
            {
                "state_dim": train.state_dim,
                "n_actions": train.n_actions,
                "hidden": ocfg.hidden,
                "action_ids": train.action_ids,
            },
        )
        # tau_u: a high quantile of the ensemble's disagreement on held-out states.
        if pcfg.tau_u is not None:
            model.tau_u = pcfg.tau_u
        elif val.episodes:
            stds = [model.stats(s.state)[1][model.act_raw(s.state, s.feasible)] for s in val.steps]
            model.tau_u = float(np.quantile(stds, ocfg.tau_u_quantile))
        return model

    @torch.no_grad()
    def stats(self, state: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x = torch.as_tensor(np.asarray(state, dtype=np.float32)).unsqueeze(0)
        qs = torch.stack([net(x)[0] for net in self.nets]).numpy()
        return qs.mean(axis=0), qs.std(axis=0)

    def values(self, state: np.ndarray) -> np.ndarray:
        return self.stats(state)[0]

    def act_raw(self, state: np.ndarray, feasible: np.ndarray) -> int:
        mean, std = self.stats(state)
        return _masked_argmax(mean - self.kappa * std, feasible)

    def act(self, state: np.ndarray, feasible: np.ndarray, graded: bool) -> int:
        a = self.act_raw(state, feasible)
        uncertain = self.tau_u is not None and self.stats(state)[1][a] > self.tau_u
        if graded and uncertain and feasible[self.escalate_index]:
            return self.escalate_index
        return a

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "nets": [n.state_dict() for n in self.nets],
                "kappa": self.kappa,
                "tau_u": self.tau_u,
                "escalate_index": self.escalate_index,
                "meta": self.meta,
            },
            path,
        )

    @classmethod
    def load(cls, path: Path) -> CQLEnsemble:
        blob = torch.load(path, weights_only=False)
        meta = blob["meta"]
        nets = []
        for sd in blob["nets"]:
            net = _mlp(meta["state_dim"], meta["hidden"], meta["n_actions"])
            net.load_state_dict(sd)
            net.eval()
            nets.append(net)
        return cls(nets, blob["kappa"], blob["tau_u"], blob["escalate_index"], meta)


# --- live use -------------------------------------------------------------------------------


class LearnedProposer:
    """Wraps a learned policy as the orchestrator's proposer (always inside F(s))."""

    def __init__(
        self,
        model: CQLEnsemble | TabularQ,
        action_ids: Sequence[str],
        catalogue: Catalogue,
        version: str,
    ) -> None:
        self.model = model
        self.action_ids = list(action_ids)
        self.catalogue = catalogue
        self.version = version

    def prefer(self, obs: PolicyObs, allowed: FilterResult) -> Preference:
        feasible = np.asarray([allowed.allows(self.catalogue.get(a)) for a in self.action_ids])
        idx = self.model.act(np.asarray(obs.state), feasible, obs.graded_item)
        action = self.catalogue.get(self.action_ids[idx])
        if not allowed.allows(action):  # defence in depth; cannot happen with the mask
            raise AssertionError(f"learned policy left F(s): {action.id}")
        values = self.model.values(np.asarray(obs.state))
        top = sorted(
            (i for i in range(len(self.action_ids)) if feasible[i]),
            key=lambda i: values[i],
            reverse=True,
        )[:3]
        note = ", ".join(f"{self.action_ids[i]}={values[i]:.2f}" for i in top)
        why = "uncertain on a graded task" if action == ESCALATE else "highest estimated value"
        return Preference(action, f"Learned policy {self.version}: {why} (top Q: {note})")


def load_proposer(
    policy_type: str, config: dict[str, Any], catalogue: Catalogue, version: str
) -> LearnedProposer:
    path = Path(config["model_path"])
    model: CQLEnsemble | TabularQ = (
        CQLEnsemble.load(path) if policy_type == "cql_ensemble" else TabularQ.load(path)
    )
    return LearnedProposer(model, config["action_ids"], catalogue, version)
