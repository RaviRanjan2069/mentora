"""r_t = lK*dK + lS*R_SRL + lG*R_goal - lD*R_dep - lL*R_load - c(a_t).

* dK      mean mastery change on the active goal's concepts
* R_SRL   g_smart*[goal set] + (c_{t-1} - c_t) + q_refl + omega*[SRL action learner-initiated]
* R_goal  +1 when a session goal is attained
* R_dep   1 if a hint or answer was given before any learner attempt
* R_load  unsolicited interventions above the load limit
* c(a)    action cost; ESCALATE has its own cost; WAIT costs nothing

Satisfaction ratings are logged but never rewarded. Weights are frozen per policy version.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from mentora.config.settings import RewardSettings
from mentora.logging_xapi.statements import ActionRef

ANSWER_GIVING_MOVES = frozenset({"graded_hint", "worked_example", "concept_explanation"})


@dataclass(frozen=True)
class StepOutcome:
    """What happened between the decision at t and the next decision (or session end)."""

    goal_mastery_before: float
    goal_mastery_after: float
    calibration_before: float
    calibration_after: float
    goal_set: bool = False
    g_smart: float | None = None
    q_refl: float | None = None
    learner_initiated_srl: bool = False
    goal_attained: bool = False
    gave_help_before_attempt: bool = False
    unsolicited_over_limit: int = 0


@dataclass(frozen=True)
class RewardTerms:
    delta_k: float
    r_srl: float
    r_goal: float
    r_dep: float
    r_load: float
    cost: float
    total: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def action_cost(action: ActionRef, w: RewardSettings) -> float:
    if action.move == "WAIT":
        return 0.0
    if action.move == "ESCALATE":
        return w.escalate_cost
    return w.action_cost


def compute_reward(action: ActionRef, o: StepOutcome, w: RewardSettings) -> RewardTerms:
    delta_k = o.goal_mastery_after - o.goal_mastery_before
    r_srl = (
        ((o.g_smart or 0.0) if o.goal_set else 0.0)
        + (o.calibration_before - o.calibration_after)
        + (o.q_refl or 0.0)
        + (w.omega if o.learner_initiated_srl else 0.0)
    )
    r_goal = 1.0 if o.goal_attained else 0.0
    r_dep = 1.0 if o.gave_help_before_attempt else 0.0
    r_load = float(max(o.unsolicited_over_limit, 0))
    cost = action_cost(action, w)
    total = (
        w.lambda_k * delta_k
        + w.lambda_s * r_srl
        + w.lambda_g * r_goal
        - w.lambda_d * r_dep
        - w.lambda_l * r_load
        - cost
    )
    return RewardTerms(delta_k, r_srl, r_goal, r_dep, r_load, cost, total)
