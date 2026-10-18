"""Fairness check: per-group estimated returns (gender, prior-achievement tercile). The
candidate must not show a wider gap between groups than the current policy. If no
attribute has at least two groups with enough episodes, the check cannot be evaluated,
and that counts as a failure (the gate is conservative)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from mentora.offline.ope_dr import OPEResult
from mentora.reward.dataset_builder import Dataset

ATTRIBUTES = ("gender", "prior_tercile")


@dataclass
class FairnessReport:
    ok: bool
    evaluable: bool
    gaps: dict[str, dict[str, float]] = field(default_factory=dict)  # attr -> current/candidate
    groups: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)
    note: str = ""


def _group_means(
    ope: OPEResult, data: Dataset, attr: str, min_n: int
) -> dict[str, tuple[float, int]]:
    by: dict[str, list[float]] = {}
    for v, lr in zip(ope.per_episode, ope.learners, strict=True):
        g = data.groups.get(str(lr), {}).get(attr, "unknown")
        if g != "unknown":
            by.setdefault(g, []).append(float(v))
    return {g: (float(np.mean(v)), len(v)) for g, v in by.items() if len(v) >= min_n}


def fairness_check(
    current: OPEResult, candidate: OPEResult, data: Dataset, min_group_episodes: int
) -> FairnessReport:
    report = FairnessReport(ok=True, evaluable=False)
    for attr in ATTRIBUTES:
        cur = _group_means(current, data, attr, min_group_episodes)
        new = _group_means(candidate, data, attr, min_group_episodes)
        common = sorted(set(cur) & set(new))
        if len(common) < 2:
            continue
        report.evaluable = True
        gap_cur = max(cur[g][0] for g in common) - min(cur[g][0] for g in common)
        gap_new = max(new[g][0] for g in common) - min(new[g][0] for g in common)
        report.gaps[attr] = {"current": round(gap_cur, 4), "candidate": round(gap_new, 4)}
        report.groups[attr] = {
            g: {
                "current": round(cur[g][0], 4),
                "candidate": round(new[g][0], 4),
                "episodes": float(cur[g][1]),
            }
            for g in common
        }
        if gap_new > gap_cur + 1e-9:
            report.ok = False
    if not report.evaluable:
        report.ok = False
        report.note = "Not evaluable: no attribute has two groups with enough episodes."
    return report
