"""Code each logged event into one of six study tactics (input to the tactic HMM)."""

from __future__ import annotations

from typing import Literal

from mentora.logging_xapi.statements import VERBS, Statement

Tactic = Literal["READ", "QUIZ", "HINT", "PLAN", "CHAT", "REFLECT"]
TACTICS: tuple[Tactic, ...] = ("READ", "QUIZ", "HINT", "PLAN", "CHAT", "REFLECT")
TACTIC_INDEX = {t: i for i, t in enumerate(TACTICS)}

_HINT_MOVES = {"graded_hint", "worked_example", "concept_explanation"}


def code_statement(st: Statement, srl_tags: dict[str, bool] | None = None) -> Tactic | None:
    """Map one xAPI statement to a tactic; None if it is not a study action."""
    verb = st.verb.id
    if verb == VERBS["answered"]:
        return "QUIZ"
    if verb == VERBS["experienced"]:
        return "READ"
    if verb == VERBS["asked"]:
        return "HINT"
    if verb == VERBS["received"]:
        ext = st.tutor_action
        if ext is None or ext.action.agent is None:
            return None
        if ext.action.agent == "ContentTutor" and ext.action.move in _HINT_MOVES:
            return "HINT"
        if ext.action.agent == "Planner":
            return "PLAN"
        if ext.action.agent == "ReflectionCoach":
            return "REFLECT"
        return None
    if verb == VERBS["commented"]:
        tags = srl_tags or {}
        if tags.get("goal_stated") or tags.get("plan_stated"):
            return "PLAN"
        if tags.get("self_evaluation") or tags.get("attribution"):
            return "REFLECT"
        if tags.get("help_request"):
            return "HINT"
        return "CHAT"
    return None
