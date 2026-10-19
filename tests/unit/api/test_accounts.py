"""Accounts: sign up / in, email links, profile and photo, student -> teacher requests, and
teachers seeing only their own students (D41)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from mentora import accounts as acc
from mentora.db import StoreFactory
from mentora.db import models as m

CODE = "teach-code-123"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@dataclass
class OutboxMailer:
    configured: bool = True
    sent: list[tuple[str, str, str]] = field(default_factory=list)
    reply_to: list[str | None] = field(default_factory=list)

    def send(self, to: str, subject: str, text: str, reply_to: str | None = None) -> None:
        self.sent.append((to, subject, text))
        self.reply_to.append(reply_to)

    def token(self, to: str) -> str:
        text = next(t for (addr, _, t) in reversed(self.sent) if addr == to)
        found = re.search(r"token=([\w-]+)", text)
        assert found, text
        return found.group(1)


@pytest.fixture
def mail(app: FastAPI) -> OutboxMailer:
    app.state.settings = app.state.settings.model_copy(update={"dev_teacher_code": SecretStr(CODE)})
    mailer = OutboxMailer()
    app.state.mailer = mailer
    return mailer


def signup(app: FastAPI, username: str, role: str = "learner", **extra: object) -> TestClient:
    c = TestClient(app)
    body = {
        "role": role,
        "username": username,
        "email": f"{username}@example.com",
        "password": "correct horse 42",
        "name": username.title(),
        "gender": "female",
        "accept_privacy": True,
        **extra,
    }
    r = c.post("/api/auth/signup", json=body)
    assert r.status_code == 201, r.text
    return c


def verify(app: FastAPI, c: TestClient, mail: OutboxMailer, email: str) -> None:
    assert c.post("/api/auth/verify", json={"token": mail.token(email)}).status_code == 200


def test_password_hash_roundtrip() -> None:
    stored = acc.hash_password("s3cret pass")
    assert stored.startswith("scrypt$") and "s3cret" not in stored
    assert acc.verify_password("s3cret pass", stored)
    assert not acc.verify_password("wrong", stored)
    assert not acc.verify_password("x", "garbage")


def test_signup_rules_and_teacher_code(app: FastAPI, mail: OutboxMailer) -> None:
    c = TestClient(app)
    base = {
        "role": "learner",
        "username": "asha.k",
        "email": "asha@example.com",
        "password": "correct horse 42",
        "name": "Asha",
        "accept_privacy": True,
    }
    assert c.post("/api/auth/signup", json={**base, "accept_privacy": False}).status_code == 422
    assert c.post("/api/auth/signup", json={**base, "username": "a!"}).status_code == 422
    assert c.post("/api/auth/signup", json={**base, "username": "admin"}).status_code == 422
    assert c.post("/api/auth/signup", json={**base, "email": "not-an-email"}).status_code == 422
    assert c.post("/api/auth/signup", json={**base, "password": "short"}).status_code == 422
    assert c.post("/api/auth/signup", json={**base, "password": "asha.k"}).status_code == 422
    teacher = {**base, "role": "teacher", "username": "dr.k", "email": "k@example.com"}
    assert TestClient(app).post("/api/auth/signup", json=teacher).status_code == 201  # no code
    r = c.post("/api/auth/signup", json=base)
    assert r.status_code == 201 and r.json()["verification_sent"] is True
    me = c.get("/api/me").json()
    assert me["username"] == "asha.k" and me["via"] == "account" and me["email_verified"] is False
    assert (
        c.get("/api/auth/username-available", params={"username": "ASHA.K"}).json()["available"]
        is False
    )
    dup = {**base, "username": "asha2"}
    assert TestClient(app).post("/api/auth/signup", json=dup).status_code == 409  # same email
    with app.state.session_factory() as db:
        account = db.find_one(m.Account, {"username": "asha.k"})
        assert account is not None and account.learner_id and db.get(m.Learner, account.learner_id)


def test_login_lockout_and_logout(app: FastAPI, mail: OutboxMailer) -> None:
    signup(app, "ravi")
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"login": "nobody", "password": "x"}).status_code == 401
    for _ in range(5):
        assert (
            c.post("/api/auth/login", json={"login": "ravi", "password": "nope"}).status_code == 401
        )
    locked = c.post("/api/auth/login", json={"login": "ravi", "password": "correct horse 42"})
    assert locked.status_code == 429  # locked even with the right password
    with app.state.session_factory() as db:
        account = db.find_one(m.Account, {"username": "ravi"})
        assert account is not None
        account.locked_until = None
        db.commit()
    ok = c.post(
        "/api/auth/login", json={"login": "RAVI@example.com", "password": "correct horse 42"}
    )
    assert ok.status_code == 200 and c.get("/api/me").json()["username"] == "ravi"
    assert c.post("/api/logout").status_code == 204 and c.get("/api/me").status_code == 401


def test_verify_and_reset_links_are_single_use(app: FastAPI, mail: OutboxMailer) -> None:
    c = signup(app, "meera")
    token = mail.token("meera@example.com")
    assert c.post("/api/auth/verify", json={"token": token}).status_code == 200
    assert c.post("/api/auth/verify", json={"token": token}).status_code == 400
    assert c.get("/api/me").json()["email_verified"] is True

    other = TestClient(app)
    assert other.post("/api/auth/forgot", json={"email": "unknown@example.com"}).status_code == 204
    before = len(mail.sent)
    assert other.post("/api/auth/forgot", json={"email": "meera@example.com"}).status_code == 204
    assert len(mail.sent) == before + 1
    reset = mail.token("meera@example.com")
    weak = other.post("/api/auth/reset", json={"token": reset, "password": "short"})
    assert weak.status_code == 400
    reset = (
        other.post("/api/auth/forgot", json={"email": "meera@example.com"}),
        mail.token("meera@example.com"),
    )[1]
    r = other.post("/api/auth/reset", json={"token": reset, "password": "a brand new pass 9"})
    assert r.status_code == 200
    assert (
        other.post(
            "/api/auth/reset", json={"token": reset, "password": "another pass 99"}
        ).status_code
        == 400
    )
    assert c.get("/api/me").status_code == 401  # the old device was signed out
    assert (
        TestClient(app)
        .post("/api/auth/login", json={"login": "meera", "password": "a brand new pass 9"})
        .status_code
        == 200
    )


def test_password_change_signs_out_other_devices(app: FastAPI, mail: OutboxMailer) -> None:
    phone = signup(app, "kiran")
    laptop = TestClient(app)
    laptop.post("/api/auth/login", json={"login": "kiran", "password": "correct horse 42"})
    bad = phone.post("/api/me/password", json={"current": "wrong", "new": "new pass word 77"})
    assert bad.status_code == 403
    ok = phone.post(
        "/api/me/password", json={"current": "correct horse 42", "new": "new pass word 77"}
    )
    assert ok.status_code == 204
    assert phone.get("/api/me").status_code == 200
    assert laptop.get("/api/me").status_code == 401


def test_profile_and_photo(app: FastAPI, mail: OutboxMailer) -> None:
    c = signup(app, "neha")
    r = c.patch("/api/me/profile", json={"name": "Neha S", "gender": "prefer_not_to_say"})
    assert r.status_code == 200 and r.json()["name"] == "Neha S"
    assert c.get("/api/me").json()["name"] == "Neha S"
    fake = c.post("/api/me/photo", files={"file": ("x.png", b"<svg onload=alert(1)>", "image/png")})
    assert fake.status_code == 415  # checked by content, not by name or declared type
    big = c.post("/api/me/photo", files={"file": ("x.png", PNG + b"\x00" * 400_000, "image/png")})
    assert big.status_code == 413
    assert c.post("/api/me/photo", files={"file": ("me.png", PNG, "image/png")}).json()["has_photo"]
    photo = c.get("/api/people/neha/photo")
    assert (
        photo.status_code == 200
        and photo.content == PNG
        and photo.headers["content-type"] == "image/png"
    )
    stranger = signup(app, "zoe")
    assert stranger.get("/api/people/neha/photo").status_code == 404  # students do not see students
    assert c.delete("/api/me/photo").status_code == 204
    assert c.get("/api/people/neha/photo").status_code == 404


def test_request_accept_and_teacher_sees_only_own_students(
    app: FastAPI, mail: OutboxMailer
) -> None:
    alice = signup(app, "alice")
    bob = signup(app, "bob")
    t1 = signup(app, "dr.rao", role="teacher")
    t2 = signup(app, "dr.sen", role="teacher")
    # unverified accounts cannot connect
    assert alice.post("/api/me/teachers", json={"username": "dr.rao"}).status_code == 403
    for c, email in ((alice, "alice"), (bob, "bob"), (t1, "dr.rao"), (t2, "dr.sen")):
        verify(app, c, mail, f"{email}@example.com")
    assert [
        p["username"] for p in alice.get("/api/teachers/search", params={"q": "dr"}).json()
    ] == ["dr.rao", "dr.sen"]
    assert alice.post("/api/me/teachers", json={"username": "nobody"}).status_code == 404
    assert (
        alice.post("/api/me/teachers", json={"username": "alice"}).status_code == 404
    )  # not a teacher
    link = alice.post("/api/me/teachers", json={"username": "dr.rao"}).json()
    assert link["status"] == "pending"
    assert alice.post("/api/me/teachers", json={"username": "dr.rao"}).status_code == 409
    bob_link = bob.post("/api/me/teachers", json={"username": "dr.rao"}).json()

    pending = t1.get("/api/teacher/requests").json()
    assert {p["person"]["username"] for p in pending} == {"alice", "bob"}
    assert t2.post(f"/api/teacher/requests/{link['id']}", json={"accept": True}).status_code == 404
    accepted = t1.post(f"/api/teacher/requests/{link['id']}", json={"accept": True}).json()
    assert accepted["status"] == "accepted" and accepted["learner_id"]
    assert (
        t1.post(f"/api/teacher/requests/{bob_link['id']}", json={"accept": False}).json()["status"]
        == "declined"
    )
    assert [x["status"] for x in bob.get("/api/me/teachers").json()] == ["declined"]

    # both students study; t1 sees only Alice, t2 sees nobody
    for c in (alice, bob):
        assert c.post("/api/sessions").status_code == 200
    rows = t1.get("/api/teacher/students").json()
    assert [r["username"] for r in rows] == ["alice"] and rows[0]["name"] == "Alice"
    assert t2.get("/api/teacher/students").json() == []
    with app.state.session_factory() as db:
        bob_account = db.find_one(m.Account, {"username": "bob"})
    assert bob_account is not None
    assert t1.get(f"/api/teacher/students/{bob_account.learner_id}").status_code == 404
    assert t1.get(f"/api/teacher/students/{accepted['learner_id']}").status_code == 200
    assert t1.get("/api/teacher/overview").json()["stats"]["total_students"] == 1
    assert alice.get("/api/people/dr.rao/photo").status_code == 404  # no photo yet, but allowed

    # leaving removes the link
    assert alice.delete(f"/api/me/teachers/{link['id']}").status_code == 204
    assert t1.get("/api/teacher/students").json() == []


def test_unlinked_distress_reaches_every_teacher(app: FastAPI, mail: OutboxMailer) -> None:
    lone = signup(app, "lone")
    t1 = signup(app, "dr.a", role="teacher")
    sid = lone.post("/api/sessions").json()["session_id"]
    r = lone.post(
        f"/api/sessions/{sid}/messages", json={"text": "I can't cope anymore, I feel hopeless"}
    )
    assert r.json()["escalated"]
    inbox = t1.get("/api/teacher/escalations", params={"status": "open"}).json()
    assert len(inbox) == 1  # no teacher yet: every teacher sees it
    answer = t1.post(
        f"/api/teacher/escalations/{inbox[0]['id']}/answer", json={"response": "I'm here."}
    )
    assert answer.status_code == 200


def test_deleting_an_account_removes_everything(app: FastAPI, mail: OutboxMailer) -> None:
    c = signup(app, "temp.user")
    c.post("/api/me/photo", files={"file": ("me.png", PNG, "image/png")})
    c.post("/api/sessions")
    factory: StoreFactory = app.state.session_factory
    with factory() as db:
        account = db.find_one(m.Account, {"username": "temp.user"})
        assert account is not None and account.learner_id is not None
        learner_id = account.learner_id
        assert db.count(m.Session, {"learner_id": learner_id}) == 1
    assert c.post("/api/me/account/delete", json={"password": "wrong"}).status_code == 403
    assert (
        c.post("/api/me/account/delete", json={"password": "correct horse 42"}).status_code == 204
    )
    assert c.get("/api/me").status_code == 401
    with factory() as db:
        assert db.count(m.Account, {"username": "temp.user"}) == 0
        assert db.count(m.AccountPhoto) == 0 and db.count(m.EmailToken) == 0
        assert db.get(m.Learner, learner_id) is None
        assert db.count(m.Session, {"learner_id": learner_id}) == 0
        assert db.count(m.Event, {"learner_id": learner_id}) == 0


def test_teacher_gets_a_permanent_class_code(app: FastAPI, mail: OutboxMailer) -> None:
    suggested = TestClient(app).get("/api/auth/class-code-suggestion").json()["code"]
    assert acc.is_new_class_code(suggested)
    t1 = signup(app, "dr.code", role="teacher", class_code=suggested)
    t2 = signup(app, "dr.other", role="teacher")  # no suggestion sent: a random one
    student = signup(app, "kid")
    for c, name in ((t1, "dr.code"), (t2, "dr.other"), (student, "kid")):
        verify(app, c, mail, f"{name}@example.com")
    assert t1.get("/api/teacher/class-code").json() == {"code": suggested}
    other_code = t2.get("/api/teacher/class-code").json()["code"]
    assert acc.is_new_class_code(other_code) and other_code != suggested
    with app.state.session_factory() as db:
        row = db.get(m.ClassCode, suggested)
        assert row is not None
        assert (row.teacher_username, row.teacher_name) == ("dr.code", "Dr.Code")

    # permanent: no way to change or remove it
    assert t1.put("/api/teacher/class-code", json={"code": "1234567890"}).status_code == 405
    assert t1.delete("/api/teacher/class-code").status_code == 405
    assert student.get("/api/teacher/class-code").status_code == 403

    # a taken or malformed code at sign-up is refused
    c = TestClient(app)
    base = {
        "role": "teacher",
        "username": "dr.late",
        "email": "late@example.com",
        "password": "correct horse 42",
        "name": "Late",
        "accept_privacy": True,
    }
    assert c.post("/api/auth/signup", json={**base, "class_code": suggested}).status_code == 409
    assert c.post("/api/auth/signup", json={**base, "class_code": "12AB"}).status_code == 422

    # renaming the teacher updates the copy kept with the code
    t1.patch("/api/me/profile", json={"name": "Dr. Code Rao", "gender": "male"})
    with app.state.session_factory() as db:
        row = db.get(m.ClassCode, suggested)
        assert row is not None and row.teacher_name == "Dr. Code Rao"

    # students join with it (spaces allowed); the teacher still accepts
    assert student.post("/api/me/teachers/join", json={"code": "9999999999"}).status_code == 404
    spaced = f"{suggested[:5]} {suggested[5:]}"
    link = student.post("/api/me/teachers/join", json={"code": spaced}).json()
    assert link["status"] == "pending" and link["person"]["username"] == "dr.code"
    assert student.post("/api/me/teachers/join", json={"code": suggested}).status_code == 409
    assert t1.post(f"/api/teacher/requests/{link['id']}", json={"accept": True}).status_code == 200


def test_teacher_without_a_code_gets_one(app: FastAPI, mail: OutboxMailer) -> None:
    t = signup(app, "dr.old", role="teacher")
    with app.state.session_factory() as db:  # a teacher from before codes were given at sign-up
        db.delete_many(m.ClassCode, {})
        db.commit()
    code = t.get("/api/teacher/class-code").json()["code"]
    assert acc.is_new_class_code(code)
    assert t.get("/api/teacher/class-code").json()["code"] == code


def test_deleting_a_teacher_removes_their_code(app: FastAPI, mail: OutboxMailer) -> None:
    t = signup(app, "dr.gone", role="teacher")
    with app.state.session_factory() as db:
        assert db.count(m.ClassCode) == 1
    assert (
        t.post("/api/me/account/delete", json={"password": "correct horse 42"}).status_code == 204
    )
    with app.state.session_factory() as db:
        assert db.count(m.ClassCode) == 0
