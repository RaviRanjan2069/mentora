"""Teacher console API: escalation inbox, per-decision explanations, rule editor,
course-memory review queue, and the policy approval screen."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from mentora.api.deps import (
    User,
    db_session,
    escalation_scope,
    orchestrator,
    require_teacher,
    visible_learners,
)
from mentora.db import ASC, DESC, Store
from mentora.db import models as m
from mentora.logging_xapi.statements import VERBS, Statement
from mentora.memory.store import pending_course_items, review_course_item
from mentora.orchestrator.turn import Orchestrator
from mentora.policy import registry
from mentora.safety.teacher_rules import parse_rule

router = APIRouter(prefix="/api/teacher", tags=["teacher"])
Teacher = Annotated[User, Depends(require_teacher)]
Db = Annotated[Store, Depends(db_session)]
Orch = Annotated[Orchestrator, Depends(orchestrator)]


def _short(learner_id: str) -> str:
    return learner_id.removeprefix("lrn_")[:8]


# --- escalations ------------------------------------------------------------------------------


class EscalationOut(BaseModel):
    id: int
    learner: str
    reason: str
    message: str | None
    status: str
    teacher_response: str | None
    created_at: datetime


class AnswerIn(BaseModel):
    response: str = Field(min_length=1, max_length=4000)


@router.get("/escalations")
def escalations(user: Teacher, db: Db, status: str | None = None) -> list[EscalationOut]:
    filter: dict[str, Any] = {"status": status} if status else {}
    filter.update(escalation_scope(user, db))
    rows = db.find(
        m.Escalation,
        filter,
        sort=[("created_at", DESC), ("id", DESC)],
        limit=200,
    )
    return [
        EscalationOut(
            id=e.id,
            learner=_short(e.learner_id),
            reason=e.reason,
            message=e.message,
            status=e.status,
            teacher_response=e.teacher_response,
            created_at=e.created_at,
        )
        for e in rows
    ]


@router.post("/escalations/{escalation_id}/answer")
def answer_escalation(escalation_id: int, body: AnswerIn, user: Teacher, db: Db) -> EscalationOut:
    e = db.find_one(m.Escalation, {"id": escalation_id, **escalation_scope(user, db)})
    if e is None:
        raise HTTPException(404, "Escalation not found")
    e.teacher_response = body.response
    e.status = "answered"
    e.resolved_at = datetime.now(UTC)
    db.commit()
    return EscalationOut(
        id=e.id,
        learner=_short(e.learner_id),
        reason=e.reason,
        message=e.message,
        status=e.status,
        teacher_response=e.teacher_response,
        created_at=e.created_at,
    )


# --- decisions --------------------------------------------------------------------------------


class DecisionOut(BaseModel):
    at: datetime
    learner: str
    turn: int | None
    action: str
    propensity: float
    policy_version: str
    reason: str | None
    why: str | None
    removed: dict[str, list[str]]
    feasible_count: int
    escalated: bool
    reply: str | None
    sources: list[str]


@router.get("/decisions")
def decisions(user: Teacher, db: Db, orch: Orch, limit: int = 50) -> list[DecisionOut]:
    visible = visible_learners(user, db)
    rows = db.values(
        m.Event,
        ["statement"],
        {"verb": VERBS["received"]}
        if visible is None
        else {"verb": VERBS["received"], "learner_id": {"$in": sorted(visible)}},
        sort=[("timestamp", DESC), ("seq", DESC)],
        limit=min(limit, 500),
    )
    out = []
    for (raw,) in rows:
        st = Statement.model_validate(raw)
        ext = st.tutor_action
        if ext is None:
            continue
        out.append(
            DecisionOut(
                at=st.timestamp,
                learner=_short(st.learner_id),
                turn=st.turn,
                action=ext.action.id,
                propensity=ext.propensity,
                policy_version=ext.policy_version,
                reason=ext.decision_reason,
                why=orch.catalogue.why_line(ext.action),
                removed=ext.filter_outcome.removed,
                feasible_count=len(ext.filter_outcome.feasible_action_ids),
                escalated=ext.escalated,
                reply=st.result.response if st.result else None,
                sources=ext.retrieved_passage_ids,
            )
        )
    return out


# --- rules ------------------------------------------------------------------------------------


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    rule: dict[str, Any]


class RuleOut(BaseModel):
    id: int
    name: str
    rule: dict[str, Any]
    active: bool


@router.get("/rules")
def list_rules(user: Teacher, db: Db, orch: Orch) -> list[RuleOut]:
    rows = db.find(m.TeacherRule, {"course_id": orch.course_id}, sort=[("id", ASC)])
    return [RuleOut(id=r.id, name=r.name, rule=r.rule, active=r.active) for r in rows]


@router.post("/rules", status_code=201)
def add_rule(body: RuleIn, user: Teacher, db: Db, orch: Orch) -> RuleOut:
    try:
        parse_rule(body.name, body.rule, orch.catalogue)
    except (ValueError, ValidationError, KeyError) as exc:
        raise HTTPException(422, f"Invalid rule: {exc}") from exc
    row = m.TeacherRule(
        course_id=orch.course_id, name=body.name, rule=body.rule, created_by=user.id
    )
    db.add(row)
    db.commit()
    return RuleOut(id=row.id, name=row.name, rule=row.rule, active=row.active)


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, user: Teacher, db: Db, orch: Orch) -> None:
    row = db.get(m.TeacherRule, rule_id)
    if row is None or row.course_id != orch.course_id:
        raise HTTPException(404, "Rule not found")
    db.delete(row)
    db.commit()


# --- course memory queue ---------------------------------------------------------------------


class QueueItemOut(BaseModel):
    id: int
    text: str
    created_at: datetime


class ReviewIn(BaseModel):
    approve: bool


@router.get("/memory-queue")
def memory_queue(user: Teacher, db: Db, orch: Orch) -> list[QueueItemOut]:
    return [
        QueueItemOut(id=i.id, text=i.text, created_at=i.created_at)
        for i in pending_course_items(db, orch.course_id)
    ]


@router.post("/memory-queue/{item_id}", status_code=204)
def review_memory(item_id: int, body: ReviewIn, user: Teacher, db: Db) -> None:
    try:
        review_course_item(db, item_id, body.approve)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    db.commit()


# --- policies ---------------------------------------------------------------------------------


class PolicyOut(BaseModel):
    version: str
    type: str
    status: str
    metrics: dict[str, Any]
    reasons: str | None
    approved_by: str | None
    created_at: datetime
    decided_at: datetime | None


class DecisionIn(BaseModel):
    approve: bool
    note: str = Field(min_length=1, max_length=2000)


@router.get("/policies")
def policies(user: Teacher, db: Db) -> list[PolicyOut]:
    registry.ensure_rule_policy(db)
    db.commit()
    return [
        PolicyOut(
            version=p.version,
            type=p.type,
            status=p.status,
            metrics=p.metrics,
            reasons=p.reasons,
            approved_by=p.approved_by,
            created_at=p.created_at,
            decided_at=p.decided_at,
        )
        for p in db.find(m.Policy, sort=[("created_at", DESC)])
    ]


@router.post("/policies/{version}/decision")
def decide_policy(version: str, body: DecisionIn, user: Teacher, db: Db) -> PolicyOut:
    try:
        p = registry.decide(db, version, approve=body.approve, teacher=user.id, note=body.note)
    except registry.RegistryError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return PolicyOut(
        version=p.version,
        type=p.type,
        status=p.status,
        metrics=p.metrics,
        reasons=p.reasons,
        approved_by=p.approved_by,
        created_at=p.created_at,
        decided_at=p.decided_at,
    )
