from __future__ import annotations

import pytest

from mentora.config import get_settings
from mentora.logging_xapi.statements import ActionRef
from mentora.reward.reward import StepOutcome, compute_reward

W = get_settings().reward
HINT = ActionRef(agent="ContentTutor", move="graded_hint", style="Socratic")
NEUTRAL = StepOutcome(0.4, 0.4, 0.3, 0.3)


def test_neutral_step_costs_only_the_action() -> None:
    t = compute_reward(HINT, NEUTRAL, W)
    assert (t.delta_k, t.r_srl, t.r_goal, t.r_dep, t.r_load) == (0, 0, 0, 0, 0)
    assert t.total == pytest.approx(-W.action_cost)
    assert compute_reward(ActionRef(move="WAIT"), NEUTRAL, W).total == 0.0
    esc = ActionRef(move="ESCALATE")
    assert compute_reward(esc, NEUTRAL, W).total == pytest.approx(-W.escalate_cost)


def test_knowledge_gain() -> None:
    t = compute_reward(HINT, StepOutcome(0.4, 0.55, 0.3, 0.3), W)
    assert t.delta_k == pytest.approx(0.15)
    assert t.total == pytest.approx(W.lambda_k * 0.15 - W.action_cost)


def test_srl_terms() -> None:
    o = StepOutcome(
        0.4, 0.4, 0.30, 0.20, goal_set=True, g_smart=0.8, q_refl=0.5, learner_initiated_srl=True
    )
    t = compute_reward(HINT, o, W)
    assert t.r_srl == pytest.approx(0.8 + 0.10 + 0.5 + W.omega)
    # g_smart only counts when a goal was set in this step
    t2 = compute_reward(HINT, StepOutcome(0.4, 0.4, 0.3, 0.3, g_smart=0.8), W)
    assert t2.r_srl == 0.0


def test_goal_dependency_and_load() -> None:
    t = compute_reward(
        HINT,
        StepOutcome(
            0.4,
            0.4,
            0.3,
            0.3,
            goal_attained=True,
            gave_help_before_attempt=True,
            unsolicited_over_limit=2,
        ),
        W,
    )
    assert (t.r_goal, t.r_dep, t.r_load) == (1.0, 1.0, 2.0)
    assert t.total == pytest.approx(W.lambda_g - W.lambda_d - 2 * W.lambda_l - W.action_cost)


def test_worse_calibration_is_penalised() -> None:
    t = compute_reward(HINT, StepOutcome(0.4, 0.4, 0.2, 0.35), W)
    assert t.r_srl == pytest.approx(-0.15)
