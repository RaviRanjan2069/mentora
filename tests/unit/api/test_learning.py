"""My Learning: starter banks, adaptive rounds, answers checked one by one, progress, and
teachers managing a subject's question bank (D43)."""

from __future__ import annotations

from typing import Any

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


def right_choice(app: FastAPI, q: dict[str, Any], rnd: dict[str, Any]) -> int:
    """The shown position of the right option (tests peek at the bank and the round's order)."""
    with app.state.session_factory() as db:
        bank_q = db.get(m.BankQuestion, q["id"])
        stored = db.get(m.PracticeRound, rnd["id"])
        assert bank_q is not None and stored is not None
        order = next(p["order"] for p in stored.plan if p["id"] == q["id"])
        return int(order.index(bank_q.answer))


def test_student_practice_round_and_progress(app: FastAPI) -> None:
    asha = signup(app, "asha")
    subjects = asha.get("/api/learning/subjects").json()
    names = {s["name"]: s for s in subjects}
    assert {"Java", "Python", "DBMS", "Machine Learning"} <= set(names)
    java = names["Java"]
    assert java["questions"] >= 100 and java["topics"] >= 8 and java["answered"] == 0

    rnd = asha.post(f"/api/learning/subjects/{java['id']}/rounds").json()
    assert len(rnd["questions"]) == 10
    assert all("answer" not in q or q["answer"] is None for q in rnd["questions"])
    assert asha.post(f"/api/learning/subjects/{java['id']}/rounds").json()["id"] == rnd["id"]

    first = rnd["questions"][0]
    wrong = (right_choice(app, first, rnd) + 1) % len(first["options"])
    out = asha.post(
        f"/api/learning/rounds/{rnd['id']}/answer",
        json={"question_id": first["id"], "choice": wrong},
    ).json()
    assert out["correct"] is False and out["answer"] == right_choice(app, first, rnd)
    again = {"question_id": first["id"], "choice": out["answer"]}
    assert asha.post(f"/api/learning/rounds/{rnd['id']}/answer", json=again).status_code == 409
    for q in rnd["questions"][1:]:
        out = asha.post(
            f"/api/learning/rounds/{rnd['id']}/answer",
            json={"question_id": q["id"], "choice": right_choice(app, q, rnd)},
        ).json()
    assert out["finished"] is True and out["score"] == 9

    detail = asha.get(f"/api/learning/subjects/{java['id']}").json()
    assert detail["answered"] == 10 and detail["accuracy"] == 0.9 and detail["rounds"] == 1
    assert detail["trend"][0]["accuracy"] == 0.9
    overall = asha.get("/api/learning/progress").json()
    assert overall["answered"] == 10 and overall["subjects"][0]["name"] == "Java"
    assert len(overall["timeline"]) == 1

    # the Progress page: real numbers, per day and per subject
    prog = asha.get("/api/progress/overview", params={"days": 7, "tz": 330}).json()
    assert prog["totals"]["answered"] == 10 and prog["totals"]["accuracy"] == 0.9
    assert prog["totals"]["streak"] == 1 and prog["granularity"] == "day"
    assert len(prog["labels"]) == len(prog["series"]["overall"]) == 1
    assert prog["series"]["overall"][-1] == 0.9 and prog["series"]["answered"][-1] == 10
    assert prog["subjects"][0]["name"] == "Java" and prog["subjects"][0]["answered"] == 10
    assert prog["series"]["subjects"][0]["values"][-1] == 0.9
    assert prog["activity"][0]["kind"] == "round" and prog["activity"][0]["score"] == 9
    empty = signup(app, "nobody").get("/api/progress/overview").json()
    assert empty["totals"]["answered"] == 0 and empty["subjects"] == []

    # the next round avoids the questions just asked
    nxt = asha.post(f"/api/learning/subjects/{java['id']}/rounds").json()
    assert not {q["id"] for q in nxt["questions"]} & {q["id"] for q in rnd["questions"]}
    bob = signup(app, "bob")
    assert bob.get(f"/api/learning/rounds/{nxt['id']}").status_code == 404
    assert asha.post(f"/api/learning/rounds/{nxt['id']}/finish").status_code == 410  # empty


def test_teacher_question_bank(app: FastAPI) -> None:
    ravi = signup(app, "dr.ravi", "teacher")
    other = signup(app, "dr.other", "teacher")
    asha = signup(app, "asha")
    java_id = next(
        s["id"] for s in asha.get("/api/learning/subjects").json() if s["name"] == "Java"
    )

    assert ravi.get(f"/api/bank/{java_id}").status_code == 403  # no Java folder yet
    ravi.post("/api/folders", json={"subject": "Java"})
    other.post("/api/folders", json={"subject": "Java"})
    bank = ravi.get(f"/api/bank/{java_id}").json()
    starters = [q for q in bank["questions"] if q["starter"]]
    assert len(starters) >= 100 and not any(q["mine"] for q in starters)

    new = {"topic": "Streams", "text": "What does stream().map do?",
           "options": ["Transforms each element", "Sorts", "Deletes"], "answer": 0}  # fmt: skip
    qid = ravi.post(f"/api/bank/{java_id}/questions", json=new).json()["id"]
    assert other.post(f"/api/bank/questions/{qid}", json=new).status_code == 403
    assert ravi.post(f"/api/bank/{java_id}/questions", json={**new, "answer": 7}).status_code == 422

    s0 = starters[0]
    fixed = {**{k: s0[k] for k in ("topic", "text", "options", "answer")}, "explanation": "Fixed."}
    assert other.post(f"/api/bank/questions/{s0['id']}", json=fixed).status_code == 200
    assert ravi.delete(f"/api/bank/questions/{s0['id']}").status_code == 409  # hide instead
    ravi.post(f"/api/bank/questions/{s0['id']}/hidden", json={"hidden": True})
    rows = {q["id"]: q for q in ravi.get(f"/api/bank/{java_id}").json()["questions"]}
    assert rows[s0["id"]]["edited"] and rows[s0["id"]]["hidden"]
    assert rows[qid]["mine"] and rows[qid]["author"] == "Dr.Ravi"

    csv = (
        "topic,question,option_a,option_b,option_c,option_d,answer,explanation\n"
        "Streams,Which collects to a list?,toList(),sum(),max(),count(),A,Terminal op\n"
        "Streams,,a,b,,,A,\n"
    )
    imp = ravi.post(
        f"/api/bank/{java_id}/import", files={"file": ("q.csv", csv.encode(), "text/csv")}
    )
    assert imp.json()["added"] == 1 and imp.json()["problems"][0].startswith("Row 3")
    bad = ravi.post(f"/api/bank/{java_id}/import", files={"file": ("q.csv", b"a,b\n1,2\n", "x")})
    assert bad.status_code == 422

    # hidden questions are not asked; teachers' questions are
    for _ in range(12):
        rnd = asha.post(f"/api/learning/subjects/{java_id}/rounds").json()
        assert s0["id"] not in {q["id"] for q in rnd["questions"]}
        asha.post(f"/api/learning/rounds/{rnd['id']}/answer",
                  json={"question_id": rnd["questions"][0]["id"], "choice": 0})  # fmt: skip
        asha.post(f"/api/learning/rounds/{rnd['id']}/finish")

    assert ravi.delete(f"/api/bank/questions/{qid}").status_code == 204
    assert [b["name"] for b in ravi.get("/api/bank").json()] == ["Java"]
    fid = ravi.get("/api/subjects").json()
    folder = next(f for s in fid for f in s["folders"] if f["mine"])
    asha.post(f"/api/folders/{folder['id']}/enroll")
    prac = ravi.get(f"/api/folders/{folder['id']}/practice").json()
    assert prac["students"][0]["student"]["username"] == "asha"
    assert prac["students"][0]["answered"] == 12
