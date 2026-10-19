"""AI Tutor chat: answers with history, keeps conversations, safety and offline handling (D46)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mentora.db import models as m
from mentora.llm.backends.fake import FakeLLM
from mentora.llm.backends.fallback import FallbackBackend
from mentora.llm.client import LLMClient
from mentora.llm.types import LLMRequest
from mentora.mail import LogMailer


@pytest.fixture(autouse=True)
def no_mail(app: FastAPI) -> None:
    app.state.mailer = LogMailer()


def signup(app: FastAPI, username: str, role: str = "learner") -> TestClient:
    c = TestClient(app)
    r = c.post(
        "/api/auth/signup",
        json={
            "role": role,
            "username": username,
            "email": f"{username}@example.com",
            "password": "correct horse 42",
            "name": "Asha Verma" if username == "asha" else username.title(),
            "accept_privacy": True,
        },
    )
    assert r.status_code == 201, r.text
    return c


def events(resp: Any) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in resp.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def answering(app: FastAPI) -> FakeLLM:
    def reply(req: LLMRequest) -> str:
        return f"Answer to: {req.messages[-1].content} ({len(req.messages)} messages)"

    fake = FakeLLM(default=reply)
    app.state.orchestrator.client = LLMClient(fake)
    return fake


def test_chat_answers_and_keeps_the_conversation(app: FastAPI) -> None:
    fake = answering(app)
    asha = signup(app, "asha")
    first = events(asha.post("/api/chat/ask", json={"text": "What is a Python list?"}))
    assert first[0][0] == "thread" and first[-1] == (
        "done",
        {"text": "Answer to: What is a Python list? (1 messages)"},
    )
    tid = first[0][1]["id"]
    assert "Asha Verma" in fake.requests[-1].system  # the tutor knows the student's name
    second = events(asha.post("/api/chat/ask", json={"text": "And a tuple?", "thread_id": tid}))
    assert second[-1][1]["text"].endswith("(3 messages)")  # earlier turns are sent along

    listed = asha.get("/api/chat/threads").json()
    assert [(t["id"], t["title"], t["messages"]) for t in listed] == [
        (tid, "What is a Python list?", 4)
    ]
    convo = asha.get(f"/api/chat/threads/{tid}").json()["messages"]
    assert [msg["role"] for msg in convo] == ["user", "assistant", "user", "assistant"]

    bob = signup(app, "bob")
    assert bob.get(f"/api/chat/threads/{tid}").status_code == 404
    assert bob.post("/api/chat/ask", json={"text": "hi", "thread_id": tid}).status_code == 404
    assert asha.delete(f"/api/chat/threads/{tid}").status_code == 204
    assert asha.get("/api/chat/threads").json() == []
    assert signup(app, "dr.x", "teacher").get("/api/chat/threads").status_code == 403


def test_distress_gets_support_and_alerts_teachers_without_the_model(app: FastAPI) -> None:
    fake = answering(app)
    asha = signup(app, "asha")
    before = len(fake.requests)
    ev = events(asha.post("/api/chat/ask", json={"text": "I want to kill myself"}))
    assert ev[-1][0] == "done" and ev[-1][1]["support"] is True
    assert len(fake.requests) == before
    with app.state.session_factory() as db:
        esc = db.find(m.Escalation, {"reason": "distress"})
        assert len(esc) == 1 and esc[0].message == "I want to kill myself"


def test_offline_model_is_reported_not_faked(app: FastAPI) -> None:
    primary, offline = FakeLLM(default=lambda r: "x"), FakeLLM(default=lambda r: "template")
    backend = FallbackBackend(primary, offline, retry_after_s=60, clock=lambda: 0.0)
    backend._down_until = 10.0  # the local model was just found unreachable
    app.state.orchestrator.client = LLMClient(backend)
    asha = signup(app, "asha")
    ev = events(asha.post("/api/chat/ask", json={"text": "Explain recursion"}))
    assert ev[-1][0] == "error" and ev[-1][1]["offline"] is True
    assert not offline.requests  # no template passed off as an answer
