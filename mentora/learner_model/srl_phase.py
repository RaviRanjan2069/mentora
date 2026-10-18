"""SRL phase (Zimmerman): rules on session context, corrected by the tagger."""

from __future__ import annotations

from dataclasses import dataclass

from mentora.learner_model.srl_tagger import SRLTags
from mentora.policy.catalogue import Phase

PHASES: tuple[Phase, ...] = ("forethought", "performance", "reflection")


@dataclass(frozen=True)
class PhaseContext:
    session_turn: int  # 0 for the first event of the session
    task_active: bool  # an item or exercise is in progress
    just_assessed: bool  # the last event completed a quiz/assessment
    has_active_goal: bool


def infer_phase(ctx: PhaseContext, tags: SRLTags | None = None) -> Phase:
    if ctx.just_assessed:
        phase: Phase = "reflection"
    elif ctx.task_active:
        phase = "performance"
    elif ctx.session_turn <= 1 or not ctx.has_active_goal:
        phase = "forethought"
    else:
        phase = "performance"
    if tags is not None and not ctx.task_active:
        if tags.self_evaluation or tags.attribution:
            phase = "reflection"
        elif tags.goal_stated or tags.plan_stated:
            phase = "forethought"
    return phase
