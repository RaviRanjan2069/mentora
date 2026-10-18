"""Readable rule policy, agreed with the teacher. Rules are checked in order; the first
that fires names the preferred action. If that action is not in F(s), its other style is
tried, then WAIT (or ESCALATE when it is the only feasible action)."""

from __future__ import annotations

from collections.abc import Callable

from mentora.logging_xapi.statements import ActionRef
from mentora.policy.base import PolicyObs, Preference
from mentora.policy.catalogue import ESCALATE, WAIT, Catalogue
from mentora.safety.feasibility import FilterResult

Rule = tuple[str, Callable[[PolicyObs], bool], str]

# (reason, condition, action id). Order matters.
RULES: list[Rule] = [
    (
        "Session start and no active goal",
        lambda o: o.session_start and not o.has_active_goal,
        "Planner.elicit_smart_goal.Socratic",
    ),
    (
        "New session while an earlier goal is still open: revisit it",
        lambda o: o.session_start and o.has_active_goal,
        "Planner.recall_past_goals.Socratic",
    ),
    (
        "Learner asked about planning and has a goal but no plan",
        lambda o: o.request == "plan" and o.has_active_goal and not o.has_plan,
        "Planner.decompose_plan.Socratic",
    ),
    (
        "Learner asked about planning and has no goal yet",
        lambda o: o.request == "plan" and not o.has_active_goal,
        "Planner.elicit_smart_goal.Socratic",
    ),
    (
        "Learner asked a direct question: answer it",
        lambda o: o.request == "question",
        "WAIT",
    ),
    (
        "A quiz was just completed",
        lambda o: o.quiz_completed,
        "ReflectionCoach.socratic_reflection.Socratic",
    ),
    (
        "Two or more wrong answers in a row",
        lambda o: o.consecutive_wrong >= 2,
        "ContentTutor.graded_hint.Socratic",
    ),
    (
        "Learner asked for the answer: offer a hint instead",
        lambda o: o.request == "answer",
        "ContentTutor.graded_hint.Socratic",
    ),
    (
        "Learner asked for a hint",
        lambda o: o.request == "hint",
        "ContentTutor.graded_hint.Socratic",
    ),
    (
        "Learner asked for a similar example",
        lambda o: o.request == "example",
        "ContentTutor.worked_example.Socratic",
    ),
    (
        # Reached only when a worked example is not allowed (e.g. on a graded item).
        "Learner asked for an example; a hint is the allowed alternative",
        lambda o: o.request == "example",
        "ContentTutor.graded_hint.Socratic",
    ),
    (
        "Learner asked for a practice question",
        lambda o: o.request == "practice",
        "ContentTutor.practice_item.Socratic",
    ),
    (
        "Learner asked for an explanation",
        lambda o: o.request == "explanation",
        "ContentTutor.concept_explanation.Socratic",
    ),
    (
        "A new item was presented and a confidence rating is due",
        lambda o: o.item_just_presented and o.confidence_due,
        "Monitor.confidence_check.Socratic",
    ),
]


class RulePolicy:
    def __init__(self, catalogue: Catalogue, version: str = "rule-v1") -> None:
        self.catalogue = catalogue
        self.version = version

    def prefer(self, obs: PolicyObs, allowed: FilterResult) -> Preference:
        if allowed.feasible == frozenset({ESCALATE}):
            return Preference(ESCALATE, "Only ESCALATE is allowed (well-being)")
        blocked: str | None = None
        for reason, condition, action_id in RULES:
            if not condition(obs):
                continue
            action = self.catalogue.get(action_id)
            if allowed.allows(action):
                return Preference(action, reason)
            other = "Directive" if action.style == "Socratic" else "Socratic"
            alt = ActionRef(agent=action.agent, move=action.move, style=other)
            if alt in self.catalogue and allowed.allows(alt):
                return Preference(alt, f"{reason} (other style; first choice not allowed)")
            # Not allowed in either style: remember why, and let a later rule apply.
            blocked = blocked or f"{reason}, but {action_id} is not allowed right now"
        return Preference(WAIT, blocked or "No rule fired")
