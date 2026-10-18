"""Teacher report for a candidate policy: OPE, fairness, simulation check, gate decision,
and examples of decisions the candidate would change (with explanations)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

import numpy as np

from mentora.offline.fairness import FairnessReport
from mentora.offline.ope_dr import OPEResult, StepPolicy, rule_target
from mentora.reward.dataset_builder import Dataset


def _label(action_id: str) -> str:
    parts = action_id.split(".")
    return (
        action_id if len(parts) != 3 else f"{parts[0]}: {parts[1].replace('_', ' ')} ({parts[2]})"
    )


def changed_decisions(
    data: Dataset,
    candidate: StepPolicy,
    values: Callable[[np.ndarray], np.ndarray],
    limit: int = 8,
) -> tuple[list[str], float]:
    steps = data.steps
    if not steps:
        return [], 0.0
    changed = [(s, candidate(s)) for s in steps if candidate(s) != rule_target(s)]
    rate = len(changed) / len(steps)
    pairs = Counter((data.action_ids[rule_target(s)], data.action_ids[a]) for s, a in changed)
    lines = []
    for (old, new), n in pairs.most_common(limit):
        example = next(
            s
            for s, a in changed
            if data.action_ids[a] == new and data.action_ids[rule_target(s)] == old
        )
        q = np.asarray(values(example.state))
        q_new, q_old = q[data.action_ids.index(new)], q[data.action_ids.index(old)]
        why = f" Estimated value {q_new:.2f} vs {q_old:.2f}."
        lines.append(
            f"- {n}x: rule chose **{_label(old)}**, candidate chooses **{_label(new)}**.{why}"
        )
    return lines, rate


def _ok(b: bool) -> str:
    return "pass" if b else "FAIL"


def build_report(
    *,
    version: str,
    method: str,
    n_train: int,
    n_val: int,
    current: OPEResult,
    candidate: OPEResult,
    fairness: FairnessReport,
    sim: dict[str, object],
    gate_passed: bool,
    reasons: list[str],
    changes: list[str],
    change_rate: float,
    ess_ok: bool,
    data_label: str,
) -> str:
    lines = [
        f"# Candidate policy {version} ({method})",
        "",
        f"Data: {data_label}. Training learners' sessions: {n_train}; held-out learners' "
        f"sessions used for evaluation: {n_val}.",
        "",
        "## Off-policy evaluation (doubly robust, held-out learners)",
        "",
        "| Policy | Estimated value | 90% interval | Effective sample size |",
        "|---|---|---|---|",
        f"| current (rule) | {current.value:.3f} | {current.lcb:.3f} to {current.ucb:.3f} | "
        f"{current.effective_sample_size:.1f} |",
        f"| candidate | {candidate.value:.3f} | {candidate.lcb:.3f} to {candidate.ucb:.3f} | "
        f"{candidate.effective_sample_size:.1f} |",
        "",
        "A small effective sample size means the estimate rests on few sessions where the "
        "logged action matched the candidate's choice; treat it with caution.",
        "",
        "## Fairness (estimated return by group)",
        "",
    ]
    if fairness.evaluable:
        for attr, gap in fairness.gaps.items():
            lines.append(
                f"- {attr}: gap between groups {gap['current']:.3f} now, "
                f"{gap['candidate']:.3f} with the candidate"
            )
    else:
        lines.append(f"- {fairness.note}")
    lines += [
        "",
        f"## Safety check in {sim.get('label', 'simulation')}",
        "",
        f"- {sim.get('sessions')} simulated sessions, {sim.get('turns')} turns, "
        f"{sim.get('violations')} constraint violations, {sim.get('escalations')} escalations.",
        "",
        f"## Decisions the candidate would change ({change_rate:.0%} of logged steps)",
        "",
        *(changes or ["- none"]),
        "",
        "## Gate",
        "",
        f"- LCB(candidate) > value(current): {_ok(candidate.lcb > current.value)}",
        f"- enough overlap with logged data (ESS {candidate.effective_sample_size:.1f} of "
        f"{candidate.n_steps} steps): {_ok(ess_ok)}",
        f"- zero constraint violations in simulation: {_ok(sim.get('violations') == 0)}",
        f"- group gap not wider than now: {_ok(fairness.ok)}",
        "",
        (
            "**Result: candidate registered. It changes nothing until a teacher approves it.**"
            if gate_passed
            else "**Result: the current policy stays.** Reasons:"
        ),
        *(f"- {r}" for r in reasons),
    ]
    return "\n".join(lines) + "\n"
