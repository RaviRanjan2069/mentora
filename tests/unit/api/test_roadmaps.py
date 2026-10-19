"""Goals & Plans API: preview, create, tick tasks, auto-progress from practice (D44)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mentora.db import models as m
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
            "name": username.title(),
            "accept_privacy": True,
        },
    )
    assert r.status_code == 201, r.text
    return c


def test_roadmap_flow(app: FastAPI) -> None:
    asha = signup(app, "asha")
    assert "Java" in asha.get("/api/roadmaps/catalog").json()["subjects"]
    goal = {
        "goal": "How to learn Java from Basic to Advanced",
        "level": "beginner",
        "pace": "steady",
    }
    prev = asha.post("/api/roadmaps/preview", json=goal).json()
    assert prev["subject"] == "Java" and prev["source"] == "curated" and len(prev["weeks"]) >= 12
    assert asha.get("/api/roadmaps").json() == []  # preview saves nothing

    unknown = asha.post("/api/roadmaps/preview", json={**goal, "goal": "Learn to cook pasta"})
    assert unknown.status_code == 422 and "ready-made roadmaps" in unknown.json()["detail"]
    assert asha.post("/api/roadmaps/preview", json={**goal, "level": "guru"}).status_code == 422

    r = asha.post("/api/roadmaps", json=goal).json()
    assert r["progress"]["current_week"] == 1 and r["progress"]["percent"] == 0
    assert r["subject_id"] is not None
    study = r["weeks"][0]["tasks"][0]
    r = asha.post(f"/api/roadmaps/{r['id']}/tasks/{study['id']}", json={"done": True}).json()
    assert r["weeks"][0]["tasks"][0]["done"] and r["progress"]["tasks_done"] == 1

    # practising week 1's topics in My Learning ticks its practice task
    practice = next(t for t in r["weeks"][0]["tasks"] if t["kind"] == "practice")
    rnd = asha.post(
        f"/api/learning/subjects/{r['subject_id']}/rounds",
        params={"topics": ",".join(practice["topics"])},
    ).json()
    assert {q["topic"] for q in rnd["questions"]} <= set(practice["topics"])
    with app.state.session_factory() as db:
        stored = db.get(m.PracticeRound, rnd["id"])
        assert stored is not None
        for p in stored.plan:
            q = db.get(m.BankQuestion, p["id"])
            assert q is not None
            asha.post(
                f"/api/learning/rounds/{rnd['id']}/answer",
                json={"question_id": q.id, "choice": p["order"].index(q.answer)},
            )
    r = asha.get(f"/api/roadmaps/{r['id']}").json()
    ticked = next(t for t in r["weeks"][0]["tasks"] if t["kind"] == "practice")
    assert ticked["done"] and ticked["auto"] and ticked["answered"] == 10

    listed = asha.get("/api/roadmaps").json()
    assert listed[0]["subject"] == "Java" and listed[0]["progress"]["tasks_done"] == 2
    bob = signup(app, "bob")
    assert bob.get(f"/api/roadmaps/{r['id']}").status_code == 404
    assert (
        asha.post(f"/api/roadmaps/{r['id']}/status", json={"status": "archived"}).json()["status"]
        == "archived"
    )
    assert asha.delete(f"/api/roadmaps/{r['id']}").status_code == 204
    assert asha.get("/api/roadmaps").json() == []
    assert signup(app, "dr.x", "teacher").get("/api/roadmaps").status_code == 403
