"""The offline loop between policy versions:

    logs -> dataset (split by learner) -> train candidate (ensemble CQL or tabular)
    -> doubly robust OPE vs the current policy on held-out learners -> fairness check
    -> constraint check in simulation -> gate -> registry (+ teacher report)

A candidate that passes the gate is registered as 'candidate' and changes nothing until a
teacher approves it in the console. One that fails is registered as 'rejected' with the
reasons, and the current policy stays. Both are valid outcomes.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import torch

from mentora.config.settings import Settings
from mentora.db import StoreFactory, connect
from mentora.db.client import drop_mock
from mentora.offline.fairness import fairness_check
from mentora.offline.ope_dr import evaluate, model_target, rule_target
from mentora.offline.policies import CQLEnsemble, LearnedProposer, TabularQ
from mentora.offline.report import build_report, changed_decisions
from mentora.offline.simulator import run_simulation
from mentora.policy import registry
from mentora.policy.catalogue import default_catalogue
from mentora.reward.dataset_builder import Dataset, build_dataset, split_by_learner


@dataclass
class PipelineResult:
    status: str  # "candidate" | "rejected" | "insufficient_data"
    version: str | None = None
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    report_markdown: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fingerprint(data: Dataset) -> str:
    h = hashlib.sha256()
    for e in data.episodes:
        for s in e.steps:
            h.update(f"{e.session_id}:{s.t}:{s.action}:{s.reward:.6f}".encode())
    return h.hexdigest()[:10]


def train_candidate(
    train: Dataset, val: Dataset, settings: Settings, method: str
) -> CQLEnsemble | TabularQ:
    torch.manual_seed(settings.policy.seed)
    np.random.seed(settings.policy.seed)
    if method == "tabular":
        return TabularQ.fit(train, settings.policy, settings.offline)
    return CQLEnsemble.fit(train, val, default_catalogue(), settings.policy, settings.offline)


def simulate_candidate(
    settings: Settings, model: CQLEnsemble | TabularQ, action_ids: list[str], version: str
) -> dict[str, object]:
    """Run the candidate in deploy mode against simulated learners in a throwaway database."""
    url = f"mongomock://sim_{uuid.uuid4().hex[:12]}"  # in memory, never the real database
    try:
        factory = connect(url)
        proposer = LearnedProposer(model, action_ids, default_catalogue(), version)
        stats = run_simulation(
            settings,
            factory,
            n_sessions=settings.offline.sim_sessions,
            turns=settings.offline.sim_turns,
            seed=settings.policy.seed + 1,
            proposer=proposer,
            policy_mode="deploy",
        )
    finally:
        drop_mock(url)
    return stats.as_dict()


def run_offline_pipeline(
    settings: Settings,
    session_factory: StoreFactory | None = None,
    *,
    method: str | None = None,
    data_label: str = "logged sessions",
    register: bool = True,
) -> PipelineResult:
    cfg, pcfg = settings.offline, settings.policy
    method = method or cfg.method
    factory = session_factory or connect(settings.database_url)
    catalogue = default_catalogue()
    data = build_dataset(factory, catalogue)
    if len(data.episodes) < cfg.min_episodes or len(data.learners) < 3:
        return PipelineResult(
            "insufficient_data",
            reasons=[
                f"{len(data.episodes)} closed sessions from {len(data.learners)} learners; need at "
                f"least {cfg.min_episodes} sessions and 3 learners. The current policy stays."
            ],
        )

    train, val = split_by_learner(data, cfg.val_fraction, pcfg.seed)
    model = train_candidate(train, val, settings, method)
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    version = f"{method}-{stamp}-{_fingerprint(data)}"

    ope_args = dict(
        gamma=pcfg.gamma,
        clip=cfg.weight_clip,
        iterations=cfg.fqe_iterations,
        alpha=cfg.ridge_alpha,
        bootstrap=cfg.bootstrap,
        lcb_alpha=cfg.lcb_alpha,
        seed=pcfg.seed,
    )
    pi_new = model_target(model)
    current = evaluate(val, rule_target, **ope_args)  # type: ignore[arg-type]
    candidate = evaluate(val, pi_new, **ope_args)  # type: ignore[arg-type]
    fairness = fairness_check(current, candidate, val, cfg.fairness_min_group_episodes)
    sim = simulate_candidate(settings, model, data.action_ids, version)

    reasons = []
    if not candidate.lcb > current.value:
        reasons.append(
            f"Lower confidence bound of the candidate ({candidate.lcb:.3f}) is not "
            f"above the current policy's estimated value ({current.value:.3f})."
        )
    min_ess = cfg.min_ess_fraction * candidate.n_steps
    ess_ok = candidate.effective_sample_size >= min_ess
    if not ess_ok:
        reasons.append(
            f"Too little overlap with the logged data: effective sample size "
            f"{candidate.effective_sample_size:.1f} < {min_ess:.1f} "
            f"({cfg.min_ess_fraction:.0%} of {candidate.n_steps} steps), so the estimate is "
            "mostly model extrapolation."
        )
    if sim["violations"] != 0:
        reasons.append(f"{sim['violations']} constraint violations in simulation.")
    if not fairness.ok:
        reasons.append(fairness.note or "The gap between groups would widen.")
    passed = not reasons

    changes, change_rate = changed_decisions(val, pi_new, model.values)
    report = build_report(
        version=version,
        method=method,
        n_train=len(train.episodes),
        n_val=len(val.episodes),
        current=current,
        candidate=candidate,
        fairness=fairness,
        sim=sim,
        gate_passed=passed,
        reasons=reasons,
        changes=changes,
        change_rate=change_rate,
        ess_ok=ess_ok,
        data_label=data_label,
    )
    suffix = "pt" if method == "cql_ensemble" else "json"
    path = settings.learner_model.model_dir / "policies" / f"{version}.{suffix}"
    model.save(path)
    metrics: dict[str, Any] = {
        "ope_current": current.summary(),
        "ope_candidate": candidate.summary(),
        "fairness": {"ok": fairness.ok, "gaps": fairness.gaps, "note": fairness.note},
        "simulation": sim,
        "changed_decision_rate": round(change_rate, 3),
        "reward_weights": settings.reward.model_dump(),
        "data_fingerprint": _fingerprint(data),
        "report_markdown": report,
    }
    status = "candidate" if passed else "rejected"
    if register:
        with factory.begin() as db:
            registry.ensure_rule_policy(db)
            registry.register_candidate(
                db,
                version,
                method,
                {
                    "model_path": str(path),
                    "action_ids": data.action_ids,
                    "kappa": pcfg.kappa,
                    "tau_u": getattr(model, "tau_u", None),
                    "seed": pcfg.seed,
                },
                metrics,
                "Passed the offline gate; awaiting teacher approval."
                if passed
                else "Did not pass the offline gate: " + " ".join(reasons),
                status=status,
            )
    return PipelineResult(status, version, reasons, metrics, report)
