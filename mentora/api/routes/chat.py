"""AI Tutor chat: ask anything, like a general chat assistant, with the student's name (D46).

A direct conversation with the language model, separate from the research tutor pipeline
(orchestrator) so answers are plain explanations rather than Socratic moves. Safety stays:
a message showing distress is not sent to the model; the student gets the support message and
their teachers get an escalation. While the local model is unreachable the chat says so instead
of replying with offline templates.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from queue import Queue
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from mentora.accounts import RateLimiter
from mentora.api.deps import User, db_session, get_orchestrator, require_learner
from mentora.api.routes.accounts import _account
from mentora.db import Store
from mentora.db import models as m
from mentora.llm.backends.fallback import FallbackBackend
from mentora.llm.types import LLMBackend, LLMError, LLMRequest, Message
from mentora.safety.wellbeing import detect_distress, support_message

router = APIRouter(prefix="/api/chat", tags=["chat"])
log = logging.getLogger("mentora.chat")

Db = Annotated[Store, Depends(db_session)]
Learner = Annotated[User, Depends(require_learner)]

HISTORY = 12  # earlier messages sent along for context
MAX_THREADS = 50
OFFLINE = (
    "The AI tutor is offline right now: its model runs on a computer that is switched off. "
    "Please try again later. Meanwhile you can practise in My Learning."
)
SYSTEM = (
    "You are Mentora, a friendly and expert AI tutor for students. The student's name is {name}. "
    "Answer any question clearly and correctly, like a patient teacher: start with the direct "
    "answer, then explain step by step, with a short example (code in fenced Markdown blocks "
    "when it helps). Use simple language, short paragraphs and lists. If you are not sure, say "
    "so instead of guessing. Do not help with cheating on graded exams, with anything harmful, "
    "or with personal data of other people. Keep answers focused; offer to go deeper."
)


def _limiter(request: Request) -> RateLimiter:
    limits: dict[str, RateLimiter] = request.app.state.rate_limits
    if "chat" not in limits:
        limits["chat"] = RateLimiter(20, 60)  # messages per minute per student
    return limits["chat"]


class ThreadSummary(BaseModel):
    id: int
    title: str
    updated_at: datetime
    messages: int


class ThreadOut(BaseModel):
    id: int
    title: str
    messages: list[dict[str, Any]]


@router.get("/threads")
def threads(user: Learner, db: Db) -> list[ThreadSummary]:
    account = _account(db, user)
    rows = db.find(
        m.ChatThread, {"student_id": account.id}, sort=[("updated_at", -1)], limit=MAX_THREADS
    )
    return [
        ThreadSummary(id=t.id, title=t.title, updated_at=t.updated_at, messages=len(t.messages))
        for t in rows
    ]


def _mine(db: Store, user: User, thread_id: int) -> m.ChatThread:
    thread = db.get(m.ChatThread, thread_id)
    if thread is None or thread.student_id != user.account_id:
        raise HTTPException(404, "No such conversation.")
    return thread


@router.get("/threads/{thread_id}")
def thread(thread_id: int, user: Learner, db: Db) -> ThreadOut:
    t = _mine(db, user, thread_id)
    return ThreadOut(id=t.id, title=t.title, messages=t.messages)


@router.delete("/threads/{thread_id}", status_code=204)
def delete_thread(thread_id: int, user: Learner, db: Db) -> None:
    t = _mine(db, user, thread_id)
    db.delete_many(m.ChatThread, {"id": t.id})
    db.commit()


class AskIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    thread_id: int | None = None


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _title(text: str) -> str:
    words = " ".join(text.split())
    return words if len(words) <= 60 else words[:57].rsplit(" ", 1)[0] + "…"


@router.post("/ask")
def ask(body: AskIn, request: Request, user: Learner, db: Db) -> StreamingResponse:
    """Server-sent events: ``thread`` {id}, then ``delta`` {text} pieces of the reply, then
    ``done`` {text} (the full reply) or ``error`` {detail}."""
    account = _account(db, user)
    if not _limiter(request).allow(account.id):
        raise HTTPException(429, "You are sending messages very fast. Please wait a moment.")
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "Type a question.")
    now = datetime.now(UTC)
    if body.thread_id is not None:
        t = _mine(db, user, body.thread_id)
    else:
        if db.count(m.ChatThread, {"student_id": account.id}) >= MAX_THREADS:
            oldest = db.find_one(m.ChatThread, {"student_id": account.id}, sort=[("updated_at", 1)])
            if oldest is not None:
                db.delete(oldest)
        t = m.ChatThread(student_id=account.id, title=_title(text))
        db.add(t)
    history = [
        Message("user" if msg["role"] == "user" else "assistant", msg["text"])
        for msg in t.messages[-HISTORY:]
    ]
    t.messages = [*t.messages, {"role": "user", "text": text, "at": now}]
    t.updated_at = now
    db.commit()
    thread_id = t.id
    settings = request.app.state.settings

    distress = detect_distress(text)
    if distress.detected:
        reply = support_message(settings.safety)
        if account.learner_id:
            db.add(
                m.Escalation(learner_id=account.learner_id, reason="distress", message=text[:2000])
            )
        t.messages = [*t.messages, {"role": "assistant", "text": reply, "at": now, "support": True}]
        db.commit()

        def support() -> Iterator[str]:
            yield _sse("thread", {"id": thread_id, "title": t.title})
            yield _sse("done", {"text": reply, "support": True})

        return StreamingResponse(support(), media_type="text/event-stream")

    backend: LLMBackend | None = get_orchestrator(request.app.state).client.backend
    if isinstance(backend, FallbackBackend):
        backend = None if backend.degraded else backend.primary
    if backend is None or getattr(backend, "name", "") == "offline":

        def offline() -> Iterator[str]:
            yield _sse("thread", {"id": thread_id, "title": t.title})
            yield _sse("error", {"detail": OFFLINE, "offline": True})

        return StreamingResponse(offline(), media_type="text/event-stream")

    llm_request = LLMRequest(
        system=SYSTEM.format(name=account.name),
        messages=(*history, Message("user", text)),
        max_tokens=1500,
        prompt_id="tutor/chat",
        prompt_version=1,
    )
    queue: Queue[tuple[str, str]] = Queue()
    factory = request.app.state.session_factory

    def work() -> None:
        try:
            stream = getattr(backend, "stream", None)
            if stream is not None:
                completion = stream(llm_request, lambda piece: queue.put(("delta", piece)))
            else:
                completion = backend.complete(llm_request)
                queue.put(("delta", completion.text))
            reply = completion.text.strip()
            with factory.begin() as wdb:
                saved = wdb.get(m.ChatThread, thread_id)
                if saved is not None:
                    saved.messages = [
                        *saved.messages,
                        {"role": "assistant", "text": reply, "at": datetime.now(UTC)},
                    ]
                    saved.updated_at = datetime.now(UTC)
            queue.put(("done", reply))
        except LLMError:
            log.warning("chat model call failed", exc_info=True)
            queue.put(("error", OFFLINE))
        except Exception:
            log.exception("chat failed")
            queue.put(("error", "The tutor could not reply just now. Please try again."))

    threading.Thread(target=work, name="mentora-chat", daemon=True).start()

    def events() -> Iterator[str]:
        yield _sse("thread", {"id": thread_id, "title": t.title})
        while True:
            kind, payload = queue.get()
            if kind == "delta":
                yield _sse("delta", {"text": payload})
            elif kind == "done":
                yield _sse("done", {"text": payload})
                return
            else:
                yield _sse("error", {"detail": payload})
                return

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
