"""Structured teacher rules for the safety filter, e.g. "no PeerBroker in week 1".

Rules are data, never free text, so the filter stays deterministic:

    {"forbid": {"agent": "PeerBroker"}, "when": {"week_lte": 1}}
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from mentora.db import models as m
from mentora.logging_xapi.statements import ActionRef
from mentora.policy.catalogue import Agent, Catalogue, Phase, Style


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Forbid(_Strict):
    """Matches actions on every given field (AND). At least one field is required."""

    agent: Agent | None = None
    move: str | None = None
    style: Style | None = None
    action: str | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if not any((self.agent, self.move, self.style, self.action)):
            raise ValueError("forbid needs at least one of agent, move, style, action")
        return self

    def matches(self, a: ActionRef) -> bool:
        return (
            (self.agent is None or a.agent == self.agent)
            and (self.move is None or a.move == self.move)
            and (self.style is None or a.style == self.style)
            and (self.action is None or a.id == self.action)
        )


class When(_Strict):
    """Conditions (AND). Empty means the rule always applies."""

    week_lte: int | None = None
    week_gte: int | None = None
    graded: bool | None = None
    phase: Phase | None = None

    def holds(self, *, week: int | None, graded: bool, phase: Phase | None) -> bool:
        if self.week_lte is not None and (week is None or week > self.week_lte):
            return False
        if self.week_gte is not None and (week is None or week < self.week_gte):
            return False
        if self.graded is not None and graded != self.graded:
            return False
        return self.phase is None or phase == self.phase


class TeacherRuleSpec(_Strict):
    name: str
    forbid: Forbid
    when: When = When()

    def check_against(self, catalogue: Catalogue) -> Self:
        """Reject rules naming moves or actions that don't exist (likely typos)."""
        if self.forbid.move and self.forbid.move not in catalogue.moves:
            raise ValueError(f"rule {self.name!r}: unknown move {self.forbid.move!r}")
        if self.forbid.action:
            catalogue.get(self.forbid.action)
        if not any(self.forbid.matches(a) for a in catalogue if a.agent is not None):
            raise ValueError(
                f"rule {self.name!r} matches no agent action (WAIT and ESCALATE cannot be "
                "forbidden)"
            )
        return self


def parse_rule(name: str, rule: dict[str, object], catalogue: Catalogue) -> TeacherRuleSpec:
    return TeacherRuleSpec.model_validate({"name": name, **rule}).check_against(catalogue)


def load_teacher_rules(db: Session, course_id: int, catalogue: Catalogue) -> list[TeacherRuleSpec]:
    """Active rules for a course. A malformed rule raises: it is better to fail loudly
    than to silently ignore what a teacher asked for."""
    rows = db.scalars(
        select(m.TeacherRule)
        .where(m.TeacherRule.course_id == course_id, m.TeacherRule.active.is_(True))
        .order_by(m.TeacherRule.id)
    )
    return [parse_rule(r.name, r.rule, catalogue) for r in rows]
