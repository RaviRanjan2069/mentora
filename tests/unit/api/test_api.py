"""M7 'done when': a student launches from (simulated) Moodle and completes a demo session;
a teacher answers an escalation. Plus authorisation and privacy checks on the API."""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from mentora.api.main import create_app
from mentora.config import get_settings

from .conftest import LEARNER_ROLE, TEACHER_ROLE, Platform, dev_login, lti_launch


def _demo_session(c: TestClient) -> str:
    r = c.post("/api/sessions")
    assert r.status_code == 200, r.text
    start = r.json()
    assert start["action"] == "Planner.elicit_smart_goal.Socratic"
    assert start["reply"] and start["why"].startswith("Why this suggestion:")
    assert not start["reply"].endswith(start["why"])  # why is a separate field for the UI
    sid = start["session_id"]
    assert (
        c.post(
            f"/api/sessions/{sid}/messages",
            json={"text": "My goal is to finish 2 for loop exercises today"},
        ).status_code
        == 200
    )
    items = c.get("/api/items").json()
    assert items and all("answer_key" not in i for i in items)
    item = next(i for i in items if i["text"].startswith("What is the last number"))
    assert c.post(f"/api/sessions/{sid}/quiz", json={"item_ids": [item["id"]]}).status_code == 204
    shown = c.post(f"/api/sessions/{sid}/items/{item['id']}/present").json()
    assert shown["action"] == "Monitor.confidence_check.Socratic"
    wrong = c.post(
        f"/api/sessions/{sid}/items/{item['id']}/answer",
        json={"response": "10", "confidence": 0.9, "seconds": 12},
    ).json()
    assert wrong["correct"] is False
    right = c.post(
        f"/api/sessions/{sid}/items/{item['id']}/answer",
        json={"response": "9", "confidence": 0.7, "seconds": 20},
    ).json()
    assert right["correct"] is True
    assert right["action"] == "ReflectionCoach.socratic_reflection.Socratic"  # quiz completed
    end = c.post(f"/api/sessions/{sid}/end").json()
    assert end["transitions"] == 5  # start, goal, present, 2 answers
    return sid


def test_student_lti_launch_and_demo_session_then_teacher_answers_escalation(
    app: FastAPI, platform: Platform
) -> None:
    student, resp = lti_launch(app, platform, sub="moodle-user-17", roles=[LEARNER_ROLE])
    assert resp.status_code == 303 and resp.headers["location"] == "/app/#/"
    me = student.get("/api/me").json()
    assert me["role"] == "learner" and me["via"] == "lti" and me["name"] == "Asha"
    assert "moodle-user-17" not in me["id"]  # pseudonymous id only
    _demo_session(student)

    dash = student.get("/api/me/dashboard").json()
    assert dash["goals"][0]["text"].startswith("My goal is")
    assert dash["calibration_points"] and 0 <= dash["calibration_error"] <= 1
    assert any(m["practised"] for m in dash["mastery"])
    assert dash["recent_tutor_messages"][0]["why"]

    # The learner asks for help in a way that escalates.
    sid = student.post("/api/sessions").json()["session_id"]
    esc = student.post(
        f"/api/sessions/{sid}/messages", json={"text": "I can't cope anymore, I feel hopeless"}
    ).json()
    assert esc["action"] == "ESCALATE" and esc["escalated"] and esc["support_resources"]

    teacher, resp = lti_launch(app, platform, sub="moodle-teacher-1", roles=[TEACHER_ROLE])
    assert resp.headers["location"] == "/app/#/teacher"
    inbox = teacher.get("/api/teacher/escalations", params={"status": "open"}).json()
    assert len(inbox) == 1 and inbox[0]["reason"] == "distress"
    answered = teacher.post(
        f"/api/teacher/escalations/{inbox[0]['id']}/answer",
        json={"response": "I'm here. Let's talk after class today."},
    ).json()
    assert answered["status"] == "answered"

    replies = student.get("/api/me/dashboard").json()["teacher_replies"]
    assert replies[0]["response"].startswith("I'm here")


def test_lti_launch_rejections(app: FastAPI, platform: Platform) -> None:
    _, bad_nonce = lti_launch(app, platform, sub="u1", roles=[LEARNER_ROLE], nonce="forged")
    assert bad_nonce.status_code == 401
    _, bad_state = lti_launch(app, platform, sub="u1", roles=[LEARNER_ROLE], state="forged")
    assert bad_state.status_code == 401
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _, forged = lti_launch(app, platform, sub="u1", roles=[LEARNER_ROLE], _key=other_key)
    assert forged.status_code == 401
    _, wrong_dep = lti_launch(
        app,
        platform,
        sub="u1",
        roles=[LEARNER_ROLE],
        **{"https://purl.imsglobal.org/spec/lti/claim/deployment_id": "9"},
    )
    assert wrong_dep.status_code == 401
    _, wrong_aud = lti_launch(app, platform, sub="u1", roles=[LEARNER_ROLE], aud="someone-else")
    assert wrong_aud.status_code == 401
    c = TestClient(app)
    assert (
        c.get("/lti/login", params={"iss": "https://evil.example", "login_hint": "x"}).status_code
        == 400
    )


def test_lti_not_configured(session_factory: object) -> None:
    app = create_app(get_settings(), session_factory)  # type: ignore[arg-type]
    assert TestClient(app).get("/lti/login").status_code == 503


def test_authorisation(app: FastAPI) -> None:
    anon = TestClient(app)
    assert anon.get("/api/me").status_code == 401
    assert anon.post("/api/sessions").status_code == 401
    learner = dev_login(app, "learner", "Ravi")
    teacher = dev_login(app, "teacher", "Dr K")
    assert learner.get("/api/teacher/escalations").status_code == 403
    assert teacher.post("/api/sessions").status_code == 403
    sid = learner.post("/api/sessions").json()["session_id"]
    other = dev_login(app, "learner", "Someone Else")
    assert other.post(f"/api/sessions/{sid}/messages", json={"text": "hi"}).status_code == 404
    assert other.post(f"/api/sessions/{sid}/end").status_code == 404


def test_dev_login_can_be_disabled(session_factory: object) -> None:
    s = get_settings().model_copy(update={"dev_login": False})
    app = create_app(s, session_factory)  # type: ignore[arg-type]
    r = TestClient(app).post("/api/dev/login", json={"role": "teacher", "name": "x"})
    assert r.status_code == 404


def test_dev_teacher_login_needs_code_when_set(session_factory: object) -> None:
    s = get_settings().model_copy(update={"dev_teacher_code": SecretStr("s3cret")})
    app = create_app(s, session_factory)  # type: ignore[arg-type]
    c = TestClient(app)
    assert c.post("/api/dev/login", json={"role": "teacher", "name": "x"}).status_code == 403
    bad = {"role": "teacher", "name": "x", "access_code": "nope"}
    assert c.post("/api/dev/login", json=bad).status_code == 403
    assert c.get("/api/me").status_code == 401
    assert c.post("/api/dev/login", json={"role": "learner", "name": "x"}).status_code == 200
    assert c.get("/api/teacher/escalations").status_code == 403
    ok = {"role": "teacher", "name": "x", "access_code": "s3cret"}
    assert c.post("/api/dev/login", json=ok).status_code == 200
    assert c.get("/api/teacher/escalations").status_code == 200


def test_teacher_console(app: FastAPI) -> None:
    learner = dev_login(app, "learner")
    _demo_session(learner)
    teacher = dev_login(app, "teacher", "Dr K")

    decisions = teacher.get("/api/teacher/decisions").json()
    assert decisions and all(d["reason"] for d in decisions)
    hint = next(d for d in decisions if d["action"] == "Monitor.confidence_check.Socratic")
    assert hint["why"].startswith("Why this suggestion") and hint["feasible_count"] > 1

    ok = teacher.post(
        "/api/teacher/rules",
        json={
            "name": "No peers in week 1",
            "rule": {"forbid": {"agent": "PeerBroker"}, "when": {"week_lte": 1}},
        },
    )
    assert ok.status_code == 201
    bad = teacher.post(
        "/api/teacher/rules", json={"name": "x", "rule": {"forbid": {"agent": "Wizard"}}}
    )
    assert bad.status_code == 422
    rules = teacher.get("/api/teacher/rules").json()
    assert [r["name"] for r in rules] == ["No peers in week 1"]
    assert teacher.delete(f"/api/teacher/rules/{rules[0]['id']}").status_code == 204

    policies = teacher.get("/api/teacher/policies").json()
    assert policies[0]["version"] == "rule-v1" and policies[0]["status"] == "active"
    assert (
        teacher.post(
            "/api/teacher/policies/rule-v1/decision", json={"approve": True, "note": "x"}
        ).status_code
        == 409
    )
    assert teacher.get("/api/teacher/memory-queue").json() == []


def test_my_memory_view_and_delete(app: FastAPI) -> None:
    from mentora.db import models as m

    learner = dev_login(app, "learner", "Mem")
    me = learner.get("/api/me").json()
    with app.state.session_factory.begin() as db:
        course_id = app.state.orchestrator.course_id
        db.add(
            m.MemoryItem(
                scope="learner",
                learner_id=me["id"],
                course_id=course_id,
                text="Prefers short examples",
                status="active",
            )
        )
    items = learner.get("/api/me/memory").json()
    assert [i["text"] for i in items] == ["Prefers short examples"]
    assert learner.delete(f"/api/me/memory/{items[0]['id']}").status_code == 204
    assert learner.get("/api/me/memory").json() == []
    assert learner.delete("/api/me/memory/999").status_code == 404


def test_health_home_and_search(app: FastAPI) -> None:
    c = TestClient(app)
    body = c.get("/health").json()
    assert body["status"] == "ok" and body["app"] == "Mentora" and body["llm_backend"] == "fake"
    home = c.get("/", follow_redirects=False)
    assert home.status_code == 307 and home.headers["location"] == "/app/"
    assert c.get("/favicon.ico").status_code == 200
    hits = c.get("/api/rag/search", params={"q": "range(10)"}).json()["hits"]
    assert len(hits) == 4 and "range" in hits[0]["text"]
