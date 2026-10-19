"""Subjects: teachers' folders, material (files, links, notes), quizzes and analysis (D42)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from mentora import subjects as sub
from mentora.db import models as m
from mentora.mail import LogMailer

PDF = b"%PDF-1.4\n" + b"x" * 2000


@pytest.fixture(autouse=True)
def no_mail(app: FastAPI) -> None:
    """Without a mail service, new accounts count as verified."""
    app.state.mailer = LogMailer()
    app.state.settings = app.state.settings.model_copy(update={"dev_teacher_code": SecretStr("")})


def signup(app: FastAPI, username: str, role: str = "learner", name: str = "") -> TestClient:
    c = TestClient(app)
    r = c.post(
        "/api/auth/signup",
        json={
            "role": role,
            "username": username,
            "email": f"{username}@example.com",
            "password": "correct horse 42",
            "name": name or username.title(),
            "accept_privacy": True,
        },
    )
    assert r.status_code == 201, r.text
    return c


QUESTIONS: list[dict[str, Any]] = [
    {"kind": "single", "text": "Java runs on the ...", "options": ["JVM", "CLR"], "answer": [0],
     "topic": "Basics"},
    {"kind": "multiple", "text": "Primitive types?", "options": ["int", "String", "char"],
     "answer": [0, 2], "points": 2, "topic": "Types"},
    {"kind": "true_false", "text": "Java is compiled to bytecode.", "answer": [0],
     "topic": "Basics"},
    {"kind": "short", "text": "Keyword to inherit a class?", "answer": ["extends"],
     "topic": "OOP"},
]  # fmt: skip


def test_subjects_folders_and_enrolment(app: FastAPI) -> None:
    ravi = signup(app, "dr.ravi", "teacher", "Dr. Ravi Singh")
    other = signup(app, "dr.other", "teacher")
    asha = signup(app, "asha")

    names = [s["name"] for s in asha.get("/api/subjects").json()]
    assert {"Java", "Python", "DBMS", "Machine Learning"} <= set(names)

    assert asha.post("/api/folders", json={"subject": "Java"}).status_code == 403
    folder = ravi.post("/api/folders", json={"subject": " java ", "about": "Core Java"}).json()
    assert (
        folder["subject"] == "Java"
        and folder["mine"]
        and folder["teacher"]["name"] == ("Dr. Ravi Singh")
    )
    assert ravi.post("/api/folders", json={"subject": "JAVA"}).status_code == 409
    new = other.post("/api/folders", json={"subject": "Cloud  Computing"}).json()
    assert new["subject"] == "Cloud Computing"
    java = next(s for s in asha.get("/api/subjects").json() if s["name"] == "Java")
    assert [f["teacher"]["username"] for f in java["folders"]] == ["dr.ravi"]

    fid = folder["id"]
    # not enrolled: summary only
    assert asha.get(f"/api/folders/{fid}").json()["enrolled"] is False
    assert asha.get(f"/api/folders/{fid}/resources").status_code == 403
    assert other.get(f"/api/folders/{fid}/resources").status_code == 403  # another teacher
    assert asha.post(f"/api/folders/{fid}/enroll").json()["enrolled"] is True
    assert asha.post(f"/api/folders/{fid}/enroll").status_code == 201  # twice is fine
    assert asha.get(f"/api/folders/{fid}/resources").json() == []
    students = ravi.get(f"/api/folders/{fid}/students").json()
    assert [s["student"]["username"] for s in students] == ["asha"]
    assert ravi.get("/api/people/asha/photo").status_code == 404  # allowed; no photo yet

    assert ravi.delete(f"/api/folders/{fid}/students/asha").status_code == 204
    assert asha.get(f"/api/folders/{fid}/resources").status_code == 403
    asha.post(f"/api/folders/{fid}/enroll")
    assert asha.delete(f"/api/folders/{fid}/enroll").status_code == 204
    assert asha.get(f"/api/folders/{fid}").json()["enrolled"] is False


def test_material_files_links_and_notes(app: FastAPI) -> None:
    ravi = signup(app, "dr.ravi", "teacher")
    asha = signup(app, "asha")
    fid = ravi.post("/api/folders", json={"subject": "Java"}).json()["id"]
    asha.post(f"/api/folders/{fid}/enroll")

    link = {"kind": "link", "title": "Slides", "url": "https://drive.google.com/x"}
    assert ravi.post(f"/api/folders/{fid}/resources", json=link).status_code == 201
    bad = {**link, "url": "javascript:alert(1)"}
    assert ravi.post(f"/api/folders/{fid}/resources", json=bad).status_code == 422
    note = {"kind": "note", "title": "Week 1", "text": "Classes and objects."}
    assert ravi.post(f"/api/folders/{fid}/resources", json=note).status_code == 201
    assert asha.post(f"/api/folders/{fid}/resources", json=note).status_code == 403

    up = ravi.post(
        f"/api/folders/{fid}/files",
        files={"file": ("../notes 1.pdf", PDF, "application/pdf")},
        data={"title": "Unit 1 notes"},
    )
    assert up.status_code == 201, up.text
    rid = up.json()["id"]
    assert up.json()["file_name"] == "notes 1.pdf" and up.json()["size"] == len(PDF)
    fake = ravi.post(
        f"/api/folders/{fid}/files", files={"file": ("x.pdf", b"MZ\x90\x00", "application/pdf")}
    )
    assert fake.status_code == 415
    exe = ravi.post(f"/api/folders/{fid}/files", files={"file": ("x.exe", b"MZ", "x")})
    assert exe.status_code == 415

    got = asha.get(f"/api/resources/{rid}/file")
    assert got.status_code == 200 and got.content == PDF
    assert got.headers["content-type"] == "application/pdf"
    assert got.headers["x-content-type-options"] == "nosniff"
    stranger = signup(app, "stranger")
    assert stranger.get(f"/api/resources/{rid}/file").status_code == 403
    assert [r["kind"] for r in asha.get(f"/api/folders/{fid}/resources").json()] == [
        "file",
        "note",
        "link",
    ]
    assert ravi.get("/api/teacher/storage").json()["used"] == len(PDF)

    assert ravi.delete(f"/api/resources/{rid}").status_code == 204
    with app.state.session_factory() as db:
        assert db.count(m.ResourceChunk) == 0


def test_large_files_are_chunked_and_limited(app: FastAPI) -> None:
    app.state.settings = app.state.settings.model_copy(
        update={
            "subjects": app.state.settings.subjects.model_copy(
                update={"file_max_mb": 3, "storage_total_mb": 4}
            )
        }
    )
    ravi = signup(app, "dr.ravi", "teacher")
    fid = ravi.post("/api/folders", json={"subject": "Java"}).json()["id"]
    big = b"%PDF" + bytes(range(256)) * (10 * 1024)  # 2.5 MB
    rid = ravi.post(f"/api/folders/{fid}/files", files={"file": ("a.pdf", big, "x")}).json()["id"]
    with app.state.session_factory() as db:
        assert db.count(m.ResourceChunk, {"resource_id": rid}) == 3
    assert ravi.get(f"/api/resources/{rid}/file").content == big
    too_big = b"%PDF" + b"x" * (3 * 1024 * 1024)
    r = ravi.post(f"/api/folders/{fid}/files", files={"file": ("b.pdf", too_big, "x")})
    assert r.status_code == 413
    r = ravi.post(f"/api/folders/{fid}/files", files={"file": ("c.pdf", big, "x")})
    assert r.status_code == 507  # 2.5 + 2.5 MB > 4 MB in total


def test_quiz_attempts_grading_and_analysis(app: FastAPI) -> None:
    ravi = signup(app, "dr.ravi", "teacher")
    asha = signup(app, "asha")
    bob = signup(app, "bob")
    fid = ravi.post("/api/folders", json={"subject": "Java"}).json()["id"]
    for c in (asha, bob):
        c.post(f"/api/folders/{fid}/enroll")

    bad = {"title": "Q", "questions": [{"kind": "single", "text": "?", "options": ["a"]}]}
    assert "Question 1" in ravi.post(f"/api/folders/{fid}/quizzes", json=bad).json()["detail"]
    quiz = ravi.post(
        f"/api/folders/{fid}/quizzes",
        json={"title": "Unit 1", "questions": QUESTIONS, "max_attempts": 2},
    ).json()
    qid = quiz["id"]
    assert quiz["total_points"] == 5 and quiz["questions"][0]["answer"] == [0]
    assert asha.get(f"/api/folders/{fid}/quizzes").json() == []  # not published yet
    assert asha.get(f"/api/quizzes/{qid}").status_code == 404
    ravi.post(f"/api/quizzes/{qid}", json={"title": "Unit 1", "questions": QUESTIONS,
                                            "max_attempts": 2, "published": True})  # fmt: skip
    pending = asha.get("/api/me/quizzes/pending").json()
    assert [(q["title"], q["subject"], q["questions"]) for q in pending] == [("Unit 1", "Java", 4)]
    shown = asha.get(f"/api/quizzes/{qid}").json()
    assert all("answer" not in q for q in shown["questions"]) and shown["attempts_left"] == 2

    ids = [q["id"] for q in shown["questions"]]
    att = asha.post(f"/api/quizzes/{qid}/start").json()["attempt_id"]
    assert asha.post(f"/api/quizzes/{qid}/start").json()["attempt_id"] == att  # resumes
    res = asha.post(
        f"/api/attempts/{att}/submit",
        json={"answers": {ids[0]: 0, ids[1]: [2, 0], ids[2]: 1, ids[3]: " Extends. "}},
    ).json()
    assert (res["score"], res["max_score"]) == (4, 5)
    assert asha.get("/api/me/quizzes/pending").json() == []  # taken
    assert [q["correct"] for q in res["questions"]] == [True, True, False, True]
    assert asha.post(f"/api/attempts/{att}/submit", json={"answers": {}}).status_code == 409
    assert bob.get(f"/api/attempts/{att}").status_code == 404
    assert ravi.get(f"/api/attempts/{att}").json()["student"]["username"] == "asha"

    b1 = bob.post(f"/api/quizzes/{qid}/start").json()["attempt_id"]
    bob.post(f"/api/attempts/{b1}/submit", json={"answers": {ids[0]: 1}})
    b2 = bob.post(f"/api/quizzes/{qid}/start").json()["attempt_id"]
    bob.post(f"/api/attempts/{b2}/submit", json={"answers": {ids[0]: 0, ids[2]: 0}})
    assert bob.post(f"/api/quizzes/{qid}/start").status_code == 409  # no attempts left

    # questions are frozen once taken; renaming and hiding still work
    changed = [{**QUESTIONS[0], "answer": [1]}, *QUESTIONS[1:]]
    body = {"title": "Unit 1", "questions": changed, "max_attempts": 2, "published": True}
    assert ravi.post(f"/api/quizzes/{qid}", json=body).status_code == 409
    body = {"title": "Unit one", "questions": QUESTIONS, "max_attempts": 2, "published": True}
    assert ravi.post(f"/api/quizzes/{qid}", json=body).json()["title"] == "Unit one"

    data = ravi.get(f"/api/folders/{fid}/analysis").json()
    stats = data["quizzes"][0]
    assert stats["students"] == 2 and stats["attempts"] == 3
    assert stats["average"] == pytest.approx((0.8 + 0.4) / 2, abs=1e-3)
    assert stats["questions"][0]["accuracy"] == 1.0
    rows = {r["student"]["username"]: r for r in data["students"]}
    assert rows["asha"]["average"] == 0.8 and "OOP" in rows["asha"]["strengths"]
    assert "Types" in rows["bob"]["weaknesses"]
    assert asha.get(f"/api/folders/{fid}/analysis").status_code == 403
    mine = asha.get(f"/api/folders/{fid}/my-results").json()
    assert mine["quizzes_taken"] == 1 and mine["attempts"][0]["quiz_title"] == "Unit one"

    # deleting the folder removes everything in it
    assert ravi.delete(f"/api/folders/{fid}").status_code == 204
    with app.state.session_factory() as db:
        for model in (m.Quiz, m.QuizAttempt, m.Enrollment, m.Resource):
            assert db.count(model) == 0


def test_deleting_a_teacher_deletes_their_folders(app: FastAPI) -> None:
    ravi = signup(app, "dr.ravi", "teacher")
    fid = ravi.post("/api/folders", json={"subject": "Java"}).json()["id"]
    ravi.post(f"/api/folders/{fid}/files", files={"file": ("a.pdf", PDF, "x")})
    ravi.post("/api/me/account/delete", json={"password": "correct horse 42"})
    with app.state.session_factory() as db:
        assert db.count(m.Folder) == db.count(m.ResourceChunk) == 0
        assert db.count(m.Subject) > 0  # subjects stay


def test_grading_rules() -> None:
    qs = sub.clean_questions(QUESTIONS)
    assert [q["id"] for q in qs] == ["q1", "q2", "q3", "q4"]
    assert qs[2]["options"] == ["True", "False"]
    assert sub.grade_one(qs[1], [0]) is False  # all or nothing
    assert sub.grade_one(qs[3], "EXTENDS!") is True
    assert sub.grade_one(qs[0], "x") is False
    with pytest.raises(sub.SubjectError):
        sub.clean_questions(
            [{"kind": "single", "text": "?", "options": ["a", "b"], "answer": [0, 1]}]
        )
    assert sub.safe_file_name("..\\..\\evil<>.pdf") == "evil_.pdf"
