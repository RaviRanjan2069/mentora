"""The policy state s_t: a fixed-length float vector, every feature scaled to [0, 1].
Free text never enters it (design rule 5). Feature list: docs/learner_model.md."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from mentora.config.settings import LearnerModelSettings
from mentora.learner_model.engagement import Engagement
from mentora.learner_model.srl_phase import PHASES
from mentora.learner_model.srl_tagger import INDICATORS
from mentora.policy.catalogue import Phase


@dataclass(frozen=True)
class LearnerSnapshot:
    goal_mastery: float  # mean mastery over the active goal's concepts (mean mastery if none)
    mean_mastery: float
    phase: Phase
    alpha: np.ndarray  # tactic-HMM forward posterior, length H
    indicator_counts: dict[str, int]  # SRL indicators over the last w learner turns
    calibration: float  # c-bar_t, lower is better
    engagement: Engagement
    plan_progress: float  # rho_t
    learner_initiated_share: float  # share of SRL actions started by the learner
    hint_before_attempt_rate: float
    answer_request_rate: float
    extra: dict[str, float] = field(default_factory=dict)


def feature_names(cfg: LearnerModelSettings) -> list[str]:
    return [
        "goal_mastery",
        "mean_mastery",
        *(f"phase_{p}" for p in PHASES),
        *(f"tactic_state_{i}" for i in range(cfg.hmm_states_max)),
        *(f"srl_{name}" for name in INDICATORS),
        "calibration_error",
        "sessions_per_week",
        "time_on_task",
        "idle_ratio",
        "dropout_risk",
        "plan_progress",
        "sdl_stage",
        "hint_before_attempt_rate",
        "answer_request_rate",
    ]


def sdl_stage(share: float, thresholds: tuple[float, float, float]) -> int:
    """Grow's four stages (1 dependent ... 4 self-directed) from the learner-initiated share."""
    return 1 + sum(share >= t for t in thresholds)


def _clip(x: float) -> float:
    return float(min(max(x, 0.0), 1.0))


def build_state(s: LearnerSnapshot, cfg: LearnerModelSettings, window: int) -> list[float]:
    alpha = np.zeros(cfg.hmm_states_max)
    n = min(len(s.alpha), cfg.hmm_states_max)
    alpha[:n] = s.alpha[:n]
    e = s.engagement
    vec = [
        s.goal_mastery,
        s.mean_mastery,
        *(1.0 if s.phase == p else 0.0 for p in PHASES),
        *alpha.tolist(),
        *(s.indicator_counts.get(name, 0) / window for name in INDICATORS),
        s.calibration,
        e.sessions_per_week / cfg.norm_sessions_per_week,
        e.time_on_task_hours / cfg.norm_time_on_task_hours,
        e.idle_ratio,
        e.dropout_risk,
        s.plan_progress,
        (sdl_stage(s.learner_initiated_share, cfg.sdl_thresholds) - 1) / 3,
        s.hint_before_attempt_rate,
        s.answer_request_rate,
    ]
    return [_clip(v) for v in vec]
