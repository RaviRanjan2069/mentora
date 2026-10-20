"""Customer support: complaints are saved, emailed to the support inbox and confirmed (D49)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@dataclass
class Outbox:
    configured: bool = False  # new accounts count as verified
    sent: list[tuple[str, str, str, str | None]] = field(default_factory=list)

    def send(self, to: str, subject: str, text: str, reply_to: str | None = None) -> None:
        self.sent.append((to, subject, text, reply_to))


@pytest.fixture
def outbox(app: FastAPI) -> Outbox:
    box = Outbox()
    app.state.mailer = box
    app.state.settings = app.state.settings.model_copy(
        update={"support_email": "help@mentora.example"}
    )
    return box


def signup(app: FastAPI, username: str, role: str = "learner") -> TestClient:
    c = TestClient(app)
    r = c.post(
        "/api/auth/signup",
        json={
            "role": role,
            "username": username,
            "email": f"{username}@example.com",
            "password": "correct horse 42",
            "name": username.title(),
            "accept_privacy": True,
        },
    )
    assert r.status_code == 201, r.text
    return c


def test_complaint_is_emailed_and_listed(app: FastAPI, outbox: Outbox) -> None:
    asha = signup(app, "asha")
    home = asha.get("/api/support").json()
    assert home["email"] == "help@mentora.example" and "bug" in home["categories"]
    assert home["your_email"] == "asha@example.com"
    body = {
        "category": "content",
        "subject": "Wrong answer in Java quiz",
        "message": "Question 4 marks HashMap as sorted.",
        "page": "My Learning",
    }
    t = asha.post("/api/support", json=body).json()
    assert t["number"] == "MEN-00001" and t["status"] == "open"

    to_support = next(msg for msg in outbox.sent if msg[0] == "help@mentora.example")
    assert "[MEN-00001]" in to_support[1] and "Wrong answer in Java quiz" in to_support[1]
    assert "asha@example.com" in to_support[2] and "HashMap" in to_support[2]
    assert to_support[3] == "asha@example.com"  # support replies straight to the user
    confirm = next(msg for msg in outbox.sent if msg[0] == "asha@example.com")
    assert "MEN-00001" in confirm[1]

    assert [x["number"] for x in asha.get("/api/support").json()["tickets"]] == ["MEN-00001"]
    bob = signup(app, "dr.bob", "teacher")  # teachers can complain too, and see only theirs
    assert bob.get("/api/support").json()["tickets"] == []
    urgent = {**body, "category": "teacher", "priority": "high"}
    assert bob.post("/api/support", json=urgent).json()["priority"] == "high"
    assert "[HIGH]" in outbox.sent[-2][1]  # the inbox copy is flagged
    assert bob.post("/api/support", json={**body, "priority": "panic"}).status_code == 422

    bad = asha.post("/api/support", json={**body, "category": "nonsense"})
    assert bad.status_code == 422
    assert asha.post("/api/support", json={**body, "message": "short"}).status_code == 422
    for _ in range(4):
        asha.post("/api/support", json=body)
    assert asha.post("/api/support", json=body).status_code == 429  # 5 an hour
    assert TestClient(app).get("/api/support").status_code == 401
