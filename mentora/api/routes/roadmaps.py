"""Goals & Plans: learning roadmaps from a goal (D44). Rules in mentora.roadmaps."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from mentora import practice as pr
from mentora import roadmaps as rm
from mentora.api.deps import (
    User,
    db_session,
    effective_llm_backend,
    get_orchestrator,
    require_learner,
)
from mentora.api.routes.accounts import _account
from mentora.db import Store
from mentora.db import models as m
from mentora.roadmaps import RoadmapError

router = APIRouter(prefix="/api", tags=["roadmaps"])
log = logging.getLogger("mentora.roadmaps")

Db = Annotated[Store, Depends(db_session)]
Learner = Annotated[User, Depends(require_learner)]
MAX_ACTIVE = 10


def _bad(exc: RoadmapError) -> HTTPException:
    return HTTPException(422, str(exc))


@router.get("/roadmaps/catalog")
def catalog(user: Learner) -> dict[str, Any]:
    """What the goal search offers."""
    return {
        "subjects": sorted(rm.templates()),
        "levels": rm.LEVELS,
        "paces": rm.PACES,
        "examples": [
            "Learn Java from basic to advanced",
            "Master data structures and algorithms",
            "Become a full-stack web developer",
            "Get started with machine learning",
        ],
    }


class GoalIn(BaseModel):
    goal: str = Field(max_length=300)
    level: str = "beginner"
    pace: str = "steady"


class Plan(BaseModel):
    goal: str
    subject: str
    subject_id: int | None
    source: str
    level: str
    pace: str
    weeks: list[dict[str, Any]]


def _subject_id(db: Store, name: str) -> int | None:
    pr.ensure_starter_questions(db)  # the subjects exist from the first request on
    row = db.find_one(m.Subject, {"key": name.casefold()})
    return row.id if row else None


def _plan(request: Request, db: Store, body: GoalIn) -> Plan:
    try:
        goal = rm.clean_goal(body.goal)
        subject = rm.match_subject(goal)
        if subject is not None:
            weeks = rm.from_template(subject, body.level, body.pace)
            return Plan(
                goal=goal,
                subject=subject,
                subject_id=_subject_id(db, subject),
                source="curated",
                level=body.level,
                pace=body.pace,
                weeks=weeks,
            )
        return _ai_plan(request, db, goal, body)
    except RoadmapError as exc:
        raise _bad(exc) from exc


def _ai_plan(request: Request, db: Store, goal: str, body: GoalIn) -> Plan:
    """A goal outside the template subjects: the AI model drafts the weeks (when it is online)."""
    state = request.app.state
    offline = HTTPException(
        422,
        "Mentora has ready-made roadmaps for "
        + ", ".join(sorted(rm.templates()))
        + ". For other goals it needs the AI tutor model, which is offline right now. "
        "Try one of those subjects, or again later.",
    )
    if (
        state.settings.llm.backend in ("fake", "offline")
        or effective_llm_backend(state) == "offline"
    ):
        raise offline
    from mentora.llm.prompts import RenderedPrompt

    prompt = RenderedPrompt(
        id="roadmap",
        version=1,
        system=rm.DRAFT_SYSTEM,
        user=f"Goal: {goal}\nLevel: {rm.LEVELS.get(body.level, body.level)}",
    )
    try:
        draft = get_orchestrator(state).client.generate(prompt, rm.Draft, max_tokens=1800)
        weeks = rm.from_draft(draft, body.level, body.pace)
    except RoadmapError:
        raise
    except Exception as exc:
        log.warning("roadmap draft failed for %r", goal, exc_info=True)
        raise offline from exc
    subject = " ".join(goal.split()[:8])
    return Plan(
        goal=goal,
        subject=subject,
        subject_id=None,
        source="ai",
        level=body.level,
        pace=body.pace,
        weeks=weeks,
    )


@router.post("/roadmaps/preview")
def preview(body: GoalIn, request: Request, user: Learner, db: Db) -> Plan:
    """The roadmap a goal would get, without saving it."""
    return _plan(request, db, body)


class RoadmapOut(BaseModel):
    id: int
    goal: str
    subject: str
    subject_id: int | None
    source: str
    level: str
    pace: str
    status: str
    start_date: datetime
    created_at: datetime
    weeks: list[dict[str, Any]]
    adaptations: list[dict[str, Any]]
    new_adaptations: list[str]
    progress: dict[str, Any]
    teachers: list[dict[str, Any]]


def _results(db: Store, account_id: str, subject_id: int | None) -> list[dict[str, Any]]:
    if subject_id is None:
        return []
    rounds = db.find(m.PracticeRound, {"student_id": account_id, "subject_id": subject_id})
    return pr.results_of(rounds)


def _sync(db: Store, roadmap: m.Roadmap) -> list[str]:
    """Brings auto-ticked tasks and adaptations up to date (both idempotent)."""
    if roadmap.status != "active":
        return []
    now = datetime.now(UTC)
    results = _results(db, roadmap.student_id, roadmap.subject_id)
    notes = rm.adapt(roadmap, results, now)
    changed = rm.refresh(roadmap, results, now) or bool(notes)
    if all(rm.week_done(w) for w in roadmap.weeks):
        roadmap.status, roadmap.completed_at = "completed", now
        changed = True
    if changed:
        roadmap.weeks = [dict(w) for w in roadmap.weeks]  # nested changes: mark as modified
        roadmap.updated_at = now
        db.commit()
    return notes


def _out(db: Store, roadmap: m.Roadmap, notes: list[str]) -> RoadmapOut:
    teachers = []
    if roadmap.subject_id is not None:
        for f in db.find(m.Folder, {"subject_id": roadmap.subject_id}, sort=[("id", 1)]):
            t = db.get(m.Account, f.teacher_id)
            if t is not None:
                teachers.append({"folder_id": f.id, "name": t.name, "username": t.username})
    return RoadmapOut(
        id=roadmap.id,
        goal=roadmap.goal,
        subject=roadmap.subject,
        subject_id=roadmap.subject_id,
        source=roadmap.source,
        level=roadmap.level,
        pace=roadmap.pace,
        status=roadmap.status,
        start_date=roadmap.start_date,
        created_at=roadmap.created_at,
        weeks=roadmap.weeks,
        adaptations=roadmap.adaptations,
        new_adaptations=notes,
        progress=rm.summary(roadmap, datetime.now(UTC)),
        teachers=teachers,
    )


def _mine(db: Store, user: User, roadmap_id: int) -> m.Roadmap:
    roadmap = db.get(m.Roadmap, roadmap_id)
    if roadmap is None or roadmap.student_id != user.account_id:
        raise HTTPException(404, "No such roadmap.")
    return roadmap


@router.post("/roadmaps", status_code=201)
def create(body: GoalIn, request: Request, user: Learner, db: Db) -> RoadmapOut:
    account = _account(db, user)
    if db.count(m.Roadmap, {"student_id": account.id, "status": "active"}) >= MAX_ACTIVE:
        raise HTTPException(
            409, f"You can follow up to {MAX_ACTIVE} roadmaps at once. Archive one first."
        )
    plan = _plan(request, db, body)
    roadmap = m.Roadmap(
        student_id=account.id,
        goal=plan.goal,
        subject=plan.subject,
        subject_id=plan.subject_id,
        level=plan.level,
        pace=plan.pace,
        source=plan.source,
        weeks=plan.weeks,
    )
    db.add(roadmap)
    db.commit()
    return _out(db, roadmap, [])


@router.get("/roadmaps")
def list_roadmaps(user: Learner, db: Db) -> list[dict[str, Any]]:
    account = _account(db, user)
    out = []
    for r in db.find(m.Roadmap, {"student_id": account.id}, sort=[("created_at", -1)]):
        _sync(db, r)
        p = rm.summary(r, datetime.now(UTC))
        cur = next((w for w in r.weeks if w["n"] == p["current_week"]), None)
        out.append(
            {
                "id": r.id,
                "goal": r.goal,
                "subject": r.subject,
                "status": r.status,
                "source": r.source,
                "progress": p,
                "current_title": cur["title"] if cur else None,
                "adaptations": len(r.adaptations),
            }
        )
    return out


@router.get("/roadmaps/{roadmap_id}")
def get_roadmap(roadmap_id: int, user: Learner, db: Db) -> RoadmapOut:
    roadmap = _mine(db, user, roadmap_id)
    notes = _sync(db, roadmap)
    return _out(db, roadmap, notes)


class TaskIn(BaseModel):
    done: bool


@router.post("/roadmaps/{roadmap_id}/tasks/{task_id}")
def set_task(roadmap_id: int, task_id: str, body: TaskIn, user: Learner, db: Db) -> RoadmapOut:
    roadmap = _mine(db, user, roadmap_id)
    task = next((t for w in roadmap.weeks for t in w["tasks"] if t["id"] == task_id), None)
    if task is None:
        raise HTTPException(404, "No such task.")
    now = datetime.now(UTC)
    task.update(done=body.done, done_at=now if body.done else None, auto=False)
    if not body.done and roadmap.status == "completed":
        roadmap.status, roadmap.completed_at = "active", None
    roadmap.weeks = [dict(w) for w in roadmap.weeks]
    roadmap.updated_at = now
    db.commit()
    notes = _sync(db, roadmap)
    return _out(db, roadmap, notes)


class StatusIn(BaseModel):
    status: str


@router.post("/roadmaps/{roadmap_id}/status")
def set_status(roadmap_id: int, body: StatusIn, user: Learner, db: Db) -> RoadmapOut:
    """Archive a roadmap or bring it back."""
    if body.status not in ("active", "archived"):
        raise HTTPException(422, "Status is active or archived.")
    roadmap = _mine(db, user, roadmap_id)
    roadmap.status = body.status
    db.commit()
    return _out(db, roadmap, [])


@router.delete("/roadmaps/{roadmap_id}", status_code=204)
def delete_roadmap(roadmap_id: int, user: Learner, db: Db) -> None:
    roadmap = _mine(db, user, roadmap_id)
    db.delete_many(m.Roadmap, {"id": roadmap.id})
    db.commit()
