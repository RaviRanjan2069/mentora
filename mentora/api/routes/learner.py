"""Learner API: tutoring sessions, quiz items, SRL dashboard and 'my memory'."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterator
from datetime import datetime
from queue import Queue
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from mentora.api.deps import User, db_session, orchestrator, require_learner
from mentora.course import item_concept_keys
from mentora.db import ASC, DESC, Store
from mentora.db import models as m
from mentora.learner_model.calibration import CalibrationTracker
from mentora.llm.client import streaming
from mentora.logging_xapi.statements import EXT_CONFIDENCE, VERBS, Statement
from mentora.memory.store import delete_all_learner_memory, delete_learner_item, learner_items
from mentora.orchestrator.turn import Orchestrator, TurnError, TurnResult

router = APIRouter(prefix="/api", tags=["learner"])
log = logging.getLogger("mentora.api")
Learner = Annotated[User, Depends(require_learner)]
Db = Annotated[Store, Depends(db_session)]
Orch = Annotated[Orchestrator, Depends(orchestrator)]


class TurnOut(BaseModel):
    session_id: str
    turn: int
    action: str
    reply: str | None
    why: str | None
    escalated: bool
    support_resources: bool
    sources: list[str]
    correct: bool | None = None
    phase: str = ""
    topic: str | None = None
    source_details: list[dict[str, object]] = []
    strategy: str | None = None  # what the chosen move does, in plain words
    answer_source: str | None = None  # "course" | "general" | "unverified"

    @classmethod
    def of(cls, r: TurnResult, orch: Orchestrator | None = None) -> TurnOut:
        spec = (
            orch.catalogue.moves.get(r.action_id.split(".")[1])
            if orch and "." in r.action_id
            else None
        )
        return cls(
            session_id=r.session_id,
            turn=r.turn,
            action=r.action_id,
            reply=r.reply.removesuffix(r.why).rstrip() if r.reply and r.why else r.reply,
            why=r.why,
            escalated=r.escalated,
            support_resources=r.show_support_resources,
            sources=r.passage_ids,
            correct=r.correct,
            phase=r.phase,
            topic=r.topic,
            source_details=r.sources,
            strategy=spec.description if spec else None,
            answer_source=r.answer_source,
        )


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class QuizIn(BaseModel):
    item_ids: list[int] = Field(min_length=1, max_length=50)


class AnswerIn(BaseModel):
    response: str = Field(min_length=1, max_length=2000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    seconds: float | None = Field(default=None, ge=0.0, le=36_000)


class ItemOut(BaseModel):
    id: int
    text: str
    item_type: str
    graded: bool
    concepts: list[str]


def _own_session(db: Store, user: User, session_id: str) -> m.Session:
    sess = db.get(m.Session, session_id)
    if sess is None or sess.learner_id != user.id:
        raise HTTPException(404, "Session not found")
    if sess.ended_at is not None:
        raise HTTPException(409, "Session has ended")
    return sess


def _run_with(orch: Orchestrator, fn: Callable[[], TurnResult]) -> TurnOut:
    return _run(fn, orch)


def _run(fn: Callable[[], TurnResult], orch: Orchestrator | None = None) -> TurnOut:
    try:
        return TurnOut.of(fn(), orch)
    except TurnError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/sessions")
def start_session(user: Learner, orch: Orch) -> TurnOut:
    return _run_with(orch, lambda: orch.start_session(user.id))


@router.post("/sessions/{session_id}/messages")
def send_message(session_id: str, body: MessageIn, user: Learner, db: Db, orch: Orch) -> TurnOut:
    _own_session(db, user, session_id)
    return _run_with(orch, lambda: orch.handle_message(session_id, body.text))


class _QueueSink:
    """Hands streamed reply text from the worker thread to the SSE response."""

    def __init__(self, queue: Queue[tuple[str, Any]]) -> None:
        self.queue = queue

    def begin(self, prompt_id: str) -> None:
        self.queue.put(("reset", prompt_id))

    def delta(self, text: str) -> None:
        self.queue.put(("delta", text))


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/sessions/{session_id}/messages/stream")
def stream_message(
    session_id: str, body: MessageIn, user: Learner, db: Db, orch: Orch
) -> StreamingResponse:
    """Like POST /messages, but as server-sent events: ``reset`` (a new draft starts),
    ``delta`` (reply text as it is generated), then ``done`` with the full turn (the final,
    checked reply, which replaces the draft) or ``error``."""
    _own_session(db, user, session_id)
    queue: Queue[tuple[str, Any]] = Queue()

    def work() -> None:
        try:
            with streaming(_QueueSink(queue)):
                result = orch.handle_message(session_id, body.text)
            queue.put(("done", TurnOut.of(result, orch).model_dump()))
        except TurnError as exc:
            queue.put(("error", str(exc)))
        except Exception:
            log.exception("streamed turn failed")
            queue.put(("error", "The tutor could not reply just now. Please try again."))

    threading.Thread(target=work, name="mentora-turn", daemon=True).start()

    def events() -> Iterator[str]:
        while True:
            kind, payload = queue.get()
            if kind == "reset":
                yield _sse("reset", {})
            elif kind == "delta":
                yield _sse("delta", {"text": payload})
            elif kind == "done":
                yield _sse("done", payload)
                return
            else:
                yield _sse("error", {"detail": payload})
                return

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/items")
def list_items(user: Learner, db: Db, orch: Orch) -> list[ItemOut]:
    concepts = item_concept_keys(db, orch.course_id)
    rows = db.find(m.Item, {"course_id": orch.course_id}, sort=[("id", ASC)])
    # answer_key is never sent to the browser
    return [
        ItemOut(
            id=i.id,
            text=i.text,
            item_type=i.item_type,
            graded=i.graded,
            concepts=concepts.get(i.id, []),
        )
        for i in rows
    ]


@router.post("/sessions/{session_id}/quiz", status_code=204)
def start_quiz(session_id: str, body: QuizIn, user: Learner, db: Db, orch: Orch) -> None:
    _own_session(db, user, session_id)
    orch.start_quiz(session_id, body.item_ids)


@router.post("/sessions/{session_id}/items/{item_id}/present")
def present_item(session_id: str, item_id: int, user: Learner, db: Db, orch: Orch) -> TurnOut:
    _own_session(db, user, session_id)
    return _run_with(orch, lambda: orch.present_item(session_id, item_id))


@router.post("/sessions/{session_id}/items/{item_id}/answer")
def answer_item(
    session_id: str, item_id: int, body: AnswerIn, user: Learner, db: Db, orch: Orch
) -> TurnOut:
    _own_session(db, user, session_id)
    return _run_with(
        orch,
        lambda: orch.handle_answer(
            session_id,
            item_id,
            body.response,
            confidence=body.confidence,
            response_seconds=body.seconds,
        ),
    )


class SummaryOut(BaseModel):
    session_id: str
    transitions: int


@router.post("/sessions/{session_id}/end")
def end_session(session_id: str, user: Learner, db: Db, orch: Orch) -> SummaryOut:
    _own_session(db, user, session_id)
    summary = orch.end_session(session_id)
    return SummaryOut(session_id=summary.session_id, transitions=summary.transitions)


# --- dashboard -------------------------------------------------------------------------------


class GoalOut(BaseModel):
    id: int
    text: str
    status: str
    smart_score: float | None
    progress: float
    steps: list[dict[str, object]]
    created_at: datetime


class TutorMessageOut(BaseModel):
    at: datetime
    action: str
    reply: str | None
    why: str | None


class TeacherReplyOut(BaseModel):
    id: int
    question: str | None
    response: str
    at: datetime | None


class DashboardOut(BaseModel):
    name: str
    goals: list[GoalOut]
    mastery: list[dict[str, object]]
    calibration_error: float
    calibration_points: list[dict[str, float]]
    recent_tutor_messages: list[TutorMessageOut]
    teacher_replies: list[TeacherReplyOut]


@router.get("/me/dashboard")
def dashboard(user: Learner, db: Db, orch: Orch) -> DashboardOut:
    goals = []
    for g in db.find(m.Goal, {"learner_id": user.id}, sort=[("id", DESC)], limit=10):
        plan = db.find_one(m.Plan, {"goal_id": g.id})
        goals.append(
            GoalOut(
                id=g.id,
                text=g.text,
                status=g.status,
                smart_score=g.smart_score,
                progress=plan.progress if plan else 0.0,
                steps=list(plan.steps) if plan else [],
                created_at=g.created_at,
            )
        )

    events = [Statement.model_validate(raw) for raw in _statements(db, user.id)]
    cfg = orch.settings.learner_model
    calib = CalibrationTracker(cfg.calibration_eta, cfg.calibration_init)
    for st in events:
        ext = st.result.extensions if st.result and st.result.extensions else {}
        if st.verb.id == VERBS["answered"] and EXT_CONFIDENCE in ext:
            calib.update(float(ext[EXT_CONFIDENCE]), bool(st.result and st.result.success))

    history = orch.learner_history(db, user.id, "", item_concept_keys(db, orch.course_id))
    k = orch.mastery_model.mastery(history, len(orch.course.concepts))
    practised = {x.concept for x in history}
    mastery = [
        {
            "concept": c.name,
            "key": c.key,
            "mastery": round(float(k[i]), 3),
            "practised": i in practised,
        }
        for i, c in enumerate(orch.course.concepts)
    ]

    tutor = [
        TutorMessageOut(
            at=st.timestamp,
            action=st.tutor_action.action.id,
            reply=st.result.response if st.result else None,
            why=orch.catalogue.why_line(st.tutor_action.action),
        )
        for st in events
        if st.tutor_action is not None and st.result and st.result.response
    ]
    replies = [
        TeacherReplyOut(
            id=e.id, question=e.message, response=e.teacher_response or "", at=e.resolved_at
        )
        for e in db.find(
            m.Escalation,
            {"learner_id": user.id, "teacher_response": {"$ne": None}},
            sort=[("id", DESC)],
        )
    ]
    return DashboardOut(
        name=user.name,
        goals=goals,
        mastery=mastery,
        calibration_error=round(calib.value, 3),
        calibration_points=calib.bins(),
        recent_tutor_messages=tutor[-20:][::-1],
        teacher_replies=replies,
    )


# --- my memory -----------------------------------------------------------------------------


class MemoryOut(BaseModel):
    id: int
    text: str
    quality: float
    created_at: datetime


@router.get("/me/memory")
def my_memory(user: Learner, db: Db, orch: Orch) -> list[MemoryOut]:
    return [
        MemoryOut(id=i.id, text=i.text, quality=round(i.quality, 2), created_at=i.created_at)
        for i in learner_items(db, user.id, orch.course_id)
    ]


@router.delete("/me/memory/{item_id}", status_code=204)
def delete_memory_item(item_id: int, user: Learner, db: Db) -> None:
    if not delete_learner_item(db, user.id, item_id):
        raise HTTPException(404, "Memory item not found")
    db.commit()


@router.delete("/me/memory", status_code=204)
def delete_all_memory(user: Learner, db: Db) -> None:
    delete_all_learner_memory(db, user.id)
    db.commit()


@router.get("/me/export")
def export_my_data(user: Learner, db: Db, orch: Orch) -> JSONResponse:
    """Everything stored about the learner, as one JSON download (data portability)."""
    sessions = db.find(m.Session, {"learner_id": user.id}, sort=[("started_at", ASC)])
    goals = db.find(m.Goal, {"learner_id": user.id}, sort=[("id", ASC)])
    escalations = db.find(m.Escalation, {"learner_id": user.id}, sort=[("id", ASC)])
    data = {
        "pseudonym": user.id,
        "exported_at": orch.clock(),
        "sessions": [
            {"id": s.id, "mode": s.mode, "started_at": s.started_at, "ended_at": s.ended_at}
            for s in sessions
        ],
        "goals": [
            {
                "text": g.text,
                "status": g.status,
                "smart_score": g.smart_score,
                "created_at": g.created_at,
            }
            for g in goals
        ],
        "memory": [
            {"text": i.text, "created_at": i.created_at}
            for i in learner_items(db, user.id, orch.course_id)
        ],
        "messages_to_teacher": [
            {
                "reason": e.reason,
                "message": e.message,
                "teacher_response": e.teacher_response,
                "created_at": e.created_at,
            }
            for e in escalations
        ],
        "events": _statements(db, user.id),
    }
    return JSONResponse(
        jsonable_encoder(data),
        headers={"Content-Disposition": 'attachment; filename="mentora-my-data.json"'},
    )


# --- home, concepts, resources ---------------------------------------------------------------


@router.get("/me/home")
def home(user: Learner, db: Db, orch: Orch) -> dict[str, object]:

    from mentora.analytics import learner_home

    data = learner_home(db, orch, user.id, orch.clock())
    unread = db.count(m.Escalation, {"learner_id": user.id, "teacher_response": {"$ne": None}})
    return {"name": user.name, "teacher_replies": unread, **data}


def _open_session_id(db: Store, learner_id: str) -> str | None:
    rows = db.values(
        m.Session,
        ["id"],
        {"learner_id": learner_id, "ended_at": None},
        sort=[("started_at", DESC)],
        limit=1,
    )
    return str(rows[0][0]) if rows else None


def _statements(db: Store, learner_id: str) -> list[dict[str, Any]]:
    """The learner's xAPI statements in time order."""
    return [
        raw
        for (raw,) in db.values(
            m.Event,
            ["statement"],
            {"learner_id": learner_id},
            sort=[("timestamp", ASC), ("seq", ASC)],
        )
    ]


@router.get("/me/session")
def current_session(user: Learner, db: Db, orch: Orch) -> dict[str, Any]:
    """The learner's open session, if any (so Tutor and Practice share one session), with
    its transcript so a reload shows the conversation so far."""
    sid = _open_session_id(db, user.id)
    messages: list[dict[str, Any]] = []
    for st in orch.lrs.query(session_id=sid) if sid else []:
        text = st.result.response if st.result else None
        if not text:
            continue
        if st.tutor_action is not None:
            action = st.tutor_action.action
            messages.append(
                {
                    "from": "tutor",
                    # The logged reply ends with the why line; the chat shows it separately.
                    "text": text.split(f"\n\n{orch.catalogue.why_prefix}", 1)[0],
                    "at": st.timestamp,
                    "action": action.id,
                    "why": orch.catalogue.why_line(action),
                }
            )
        elif st.verb.id.endswith("/commented"):
            messages.append({"from": "learner", "text": text, "at": st.timestamp})
    return {"session_id": sid, "messages": messages}


class ConceptOut(BaseModel):
    key: str
    name: str
    week: int | None
    prereqs: list[str]
    mastery: float
    practised: bool
    item_ids: list[int]


@router.get("/concepts")
def concepts(user: Learner, db: Db, orch: Orch) -> list[ConceptOut]:
    item_keys = item_concept_keys(db, orch.course_id)
    history = orch.learner_history(db, user.id, "", item_keys)
    k = orch.mastery_model.mastery(history, len(orch.course.concepts))
    practised = {x.concept for x in history}
    by_concept: dict[str, list[int]] = {}
    for item_id, keys in item_keys.items():
        for key in keys:
            by_concept.setdefault(key, []).append(item_id)
    return [
        ConceptOut(
            key=c.key,
            name=c.name,
            week=c.week,
            prereqs=c.prereqs,
            mastery=round(float(k[i]), 3),
            practised=i in practised,
            item_ids=sorted(by_concept.get(c.key, [])),
        )
        for i, c in enumerate(orch.course.concepts)
    ]


class ResourceOut(BaseModel):
    id: str
    section: str | None
    week: int | None
    concepts: list[str]
    source: str | None
    text: str


@router.get("/resources")
def resources(user: Learner, db: Db, orch: Orch) -> list[ResourceOut]:
    rows = db.find(
        m.CorpusPassage, {"course_id": orch.course_id}, sort=[("week", ASC), ("id", ASC)]
    )
    return [
        ResourceOut(
            id=p.id,
            section=p.section,
            week=p.week,
            concepts=list(p.concept_keys),
            source=p.source_file,
            text=p.text,
        )
        for p in rows
    ]


@router.post("/resources/{passage_id}/view", status_code=204)
def view_resource(passage_id: str, user: Learner, db: Db, orch: Orch) -> None:
    """Log that the learner opened course material (a READ event for the tactic model)."""
    from mentora.logging_xapi.lrs_client import SqlLRSClient
    from mentora.logging_xapi.statements import XAPI_BASE, lms_event

    passage = db.get(m.CorpusPassage, passage_id)
    if passage is None or passage.course_id != orch.course_id:
        raise HTTPException(404, "Resource not found")
    sid = _open_session_id(db, user.id)
    SqlLRSClient(orch.factory).store(
        lms_event(
            user.id,
            sid,
            None,
            "experienced",
            f"{XAPI_BASE}/passages/{passage_id}",
            passage.section or passage_id,
        )
    )
