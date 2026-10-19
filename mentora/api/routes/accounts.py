"""Accounts: sign up, sign in, email verification, password reset, profile and photo, and
student -> teacher requests (docs/decisions.md D41)."""

from __future__ import annotations

import hmac
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from mentora import accounts as acc
from mentora.accounts import AccountError
from mentora.api.deps import (
    Role,
    User,
    current_user,
    db_session,
    require_learner,
    require_teacher,
    sign_in,
)
from mentora.config.settings import Settings
from mentora.db import IntegrityError, Store
from mentora.db import models as m
from mentora.mail import Mailer, MailError

log = logging.getLogger("mentora.accounts")
router = APIRouter(prefix="/api", tags=["accounts"])
Db = Annotated[Store, Depends(db_session)]
Me = Annotated[User, Depends(current_user)]
Learner = Annotated[User, Depends(require_learner)]
Teacher = Annotated[User, Depends(require_teacher)]
Gender = Literal["female", "male", "non_binary", "prefer_not_to_say"]


def _settings(request: Request) -> Settings:
    s: Settings = request.app.state.settings
    return s


def _mailer(request: Request) -> Mailer:
    mailer: Mailer = request.app.state.mailer
    return mailer


def _limit(request: Request, name: str) -> None:
    limiter = request.app.state.rate_limits[name]
    ip = request.client.host if request.client else "unknown"
    if not limiter.allow(ip):
        raise HTTPException(429, "Too many attempts from this network. Please wait and try again.")


def _account(db: Store, user: User) -> m.Account:
    if user.account_id is None:
        raise HTTPException(400, "This needs a Mentora account (you signed in another way).")
    account = db.get(m.Account, user.account_id)
    if account is None:
        raise HTTPException(401, "Please sign in again.")
    return account


def _sign_in(request: Request, account: m.Account) -> None:
    user_id = account.learner_id if account.role == "learner" else f"tch_{account.id}"
    role: Role = "teacher" if account.role == "teacher" else "learner"
    user = User(
        user_id or account.id, role, account.name, "account", account.id, account.session_version
    )
    sign_in(request, user)


def _link(request: Request, path: str, token: str) -> str:
    base = _settings(request).public_base_url.rstrip("/")
    return f"{base}/app/#/{path}?token={token}"


def _send(request: Request, to: str, subject: str, text: str) -> bool:
    try:
        _mailer(request).send(to, subject, text)
        return True
    except MailError:
        log.warning("email to %s failed", to, exc_info=True)
        return False


def _send_verification(request: Request, db: Store, account: m.Account) -> bool:
    token = acc.issue_token(db, account, "verify", _settings(request).accounts.verify_hours)
    return _send(
        request,
        account.email,
        "Confirm your email for Mentora",
        f"Hi {account.name},\n\nPlease confirm your email address for your Mentora account "
        f"(user id: {account.username}):\n\n{_link(request, 'verify', token)}\n\n"
        f"The link works for {int(_settings(request).accounts.verify_hours)} hours. "
        "If you did not create this account, you can ignore this email.",
    )


def _needs_verification(request: Request, account: m.Account) -> None:
    if _mailer(request).configured and not account.email_verified:
        raise HTTPException(403, "Please confirm your email address first (check your inbox).")


class ProfileOut(BaseModel):
    username: str
    email: str
    email_verified: bool
    role: str
    name: str
    gender: str
    has_photo: bool
    photo_version: int
    created_at: datetime


def profile_of(db: Store, account: m.Account) -> ProfileOut:
    photo = db.get(m.AccountPhoto, account.id)
    return ProfileOut(
        username=account.username,
        email=account.email,
        email_verified=account.email_verified,
        role=account.role,
        name=account.name,
        gender=account.gender,
        has_photo=photo is not None,
        photo_version=int(photo.updated_at.timestamp()) if photo else 0,
        created_at=account.created_at,
    )


# --- sign up / sign in -----------------------------------------------------------------------


class SignupIn(BaseModel):
    role: Literal["learner", "teacher"]
    username: str = Field(min_length=3, max_length=30)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=80)
    gender: Gender = "prefer_not_to_say"
    teacher_code: str = Field(default="", max_length=200)
    accept_privacy: bool


@router.get("/auth/options")
def auth_options(request: Request) -> dict[str, bool]:
    """What the sign-in page offers."""
    s = _settings(request)
    return {
        "dev_login": s.dev_login,
        "email": _mailer(request).configured,
        "teacher_signup": bool(s.dev_teacher_code.get_secret_value()),
    }


@router.get("/auth/username-available")
def username_available(username: str, request: Request, db: Db) -> dict[str, Any]:
    _limit(request, "login")
    try:
        name = acc.normalize_username(username)
    except AccountError as exc:
        return {"available": False, "reason": str(exc)}
    taken = acc.username_taken(db, name)
    return {"available": not taken, "reason": "That user id is taken." if taken else None}


@router.post("/auth/signup", status_code=201)
def signup(body: SignupIn, request: Request, db: Db) -> dict[str, Any]:
    _limit(request, "signup")
    s = _settings(request)
    if not body.accept_privacy:
        raise HTTPException(422, "Please accept the privacy notice to create an account.")
    try:
        username = acc.normalize_username(body.username)
        email = acc.normalize_email(body.email)
        acc.check_password_rules(body.password, username, email, s.accounts.password_min)
    except AccountError as exc:
        raise HTTPException(422, str(exc)) from exc
    if body.role == "teacher":
        code = s.dev_teacher_code.get_secret_value()
        if not code or not hmac.compare_digest(body.teacher_code.encode(), code.encode()):
            raise HTTPException(
                403, "The teacher code is not right. Ask the Mentora administrator."
            )
    if acc.username_taken(db, username):
        raise HTTPException(409, "That user id is taken. Please choose another.")
    if db.count(m.Account, {"email": email}):
        raise HTTPException(409, "An account with this email already exists. Try signing in.")

    mailer = _mailer(request)
    account = m.Account(
        username=username,
        email=email,
        email_verified=not mailer.configured,
        role=body.role,
        name=body.name.strip(),
        gender=body.gender,
        password_hash=acc.hash_password(body.password),
        last_login_at=datetime.now(UTC),
    )
    if body.role == "learner":
        account.learner_id = acc.learner_pseudonym(account.id, s.pseudonym_salt.get_secret_value())
        db.add(m.Learner(id=account.learner_id, gender=body.gender))
    db.add(account)
    try:
        db.flush()
    except IntegrityError as exc:  # a parallel sign-up took the user id or email
        raise HTTPException(409, "That user id or email was just taken. Please try again.") from exc
    db.commit()
    sent = _send_verification(request, db, account) if mailer.configured else False
    db.commit()
    _sign_in(request, account)
    return {"profile": profile_of(db, account), "verification_sent": sent}


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=254)  # user id or email
    password: str = Field(min_length=1, max_length=128)


_DUMMY_HASH = acc.hash_password("timing-equaliser-not-a-real-password")


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Db) -> ProfileOut:
    _limit(request, "login")
    cfg = _settings(request).accounts
    account = acc.find_by_login(db, body.login)
    now = datetime.now(UTC)
    if account is None:
        acc.verify_password(body.password, _DUMMY_HASH)  # same work either way
        raise HTTPException(401, "Wrong user id, email or password.")
    if account.locked_until and account.locked_until > now:
        minutes = max(1, round((account.locked_until - now).total_seconds() / 60))
        raise HTTPException(
            429, f"Too many wrong passwords. Try again in {minutes} minutes or reset your password."
        )
    if not acc.verify_password(body.password, account.password_hash):
        account.failed_logins += 1
        if account.failed_logins >= cfg.lockout_attempts:
            account.locked_until = now + timedelta(minutes=cfg.lockout_minutes)
            account.failed_logins = 0
        db.commit()
        raise HTTPException(401, "Wrong user id, email or password.")
    account.failed_logins, account.locked_until, account.last_login_at = 0, None, now
    db.commit()
    _sign_in(request, account)
    return profile_of(db, account)


# --- email links ---------------------------------------------------------------------------


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


@router.post("/auth/verify")
def verify_email(body: TokenIn, db: Db) -> dict[str, str]:
    try:
        account = acc.use_token(db, body.token, "verify")
    except AccountError as exc:
        raise HTTPException(400, str(exc)) from exc
    account.email_verified = True
    db.commit()
    return {"username": account.username}


@router.post("/auth/resend-verification", status_code=204)
def resend_verification(request: Request, user: Me, db: Db) -> None:
    _limit(request, "email")
    account = _account(db, user)
    if account.email_verified:
        return
    if not _send_verification(request, db, account):
        raise HTTPException(502, "The email could not be sent just now. Please try again later.")
    db.commit()


class ForgotIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


@router.post("/auth/forgot", status_code=204)
def forgot_password(body: ForgotIn, request: Request, db: Db) -> None:
    """Always the same answer, so it cannot be used to find out who has an account."""
    _limit(request, "email")
    account = db.find_one(m.Account, {"email": body.email.strip().lower()})
    if account is None:
        return
    hours = _settings(request).accounts.reset_hours
    token = acc.issue_token(db, account, "reset", hours)
    db.commit()
    _send(
        request,
        account.email,
        "Reset your Mentora password",
        f"Hi {account.name},\n\nSomeone asked to reset the password of your Mentora account "
        f"(user id: {account.username}). To choose a new password, open:\n\n"
        f"{_link(request, 'reset', token)}\n\n"
        f"The link works for {int(hours * 60)} minutes and only once. "
        "If this was not you, ignore this email: your password stays the same.",
    )


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=128)


@router.post("/auth/reset")
def reset_password(body: ResetIn, request: Request, db: Db) -> ProfileOut:
    _limit(request, "login")
    try:
        account = acc.use_token(db, body.token, "reset")
        acc.check_password_rules(
            body.password, account.username, account.email, _settings(request).accounts.password_min
        )
    except AccountError as exc:
        raise HTTPException(400, str(exc)) from exc
    account.password_hash = acc.hash_password(body.password)
    account.session_version += 1  # signs out every other device
    account.failed_logins, account.locked_until = 0, None
    account.email_verified = True  # the reset link proved they own the address
    db.commit()
    _sign_in(request, account)
    return profile_of(db, account)


# --- profile ------------------------------------------------------------------------------


@router.get("/me/profile")
def my_profile(user: Me, db: Db) -> ProfileOut:
    return profile_of(db, _account(db, user))


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    gender: Gender


@router.patch("/me/profile")
def update_profile(body: ProfileIn, request: Request, user: Me, db: Db) -> ProfileOut:
    account = _account(db, user)
    account.name, account.gender = body.name.strip(), body.gender
    if account.learner_id and (learner := db.get(m.Learner, account.learner_id)):
        learner.gender = body.gender
    db.commit()
    _sign_in(request, account)  # the name shown in the header
    return profile_of(db, account)


@router.post("/me/photo")
async def upload_photo(file: UploadFile, user: Me, db: Db, request: Request) -> ProfileOut:
    limit = _settings(request).accounts.photo_max_kb * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"Please use a photo under {limit // 1024} KB.")
    try:
        kind = acc.photo_type(data)
    except AccountError as exc:
        raise HTTPException(415, str(exc)) from exc
    account = _account(db, user)
    photo = db.get(m.AccountPhoto, account.id)
    if photo is None:
        db.add(m.AccountPhoto(id=account.id, content_type=kind, data=data))
    else:
        photo.content_type, photo.data, photo.updated_at = kind, data, datetime.now(UTC)
    db.commit()
    return profile_of(db, account)


@router.delete("/me/photo", status_code=204)
def delete_photo(user: Me, db: Db) -> None:
    db.delete_many(m.AccountPhoto, {"id": _account(db, user).id})
    db.commit()


def _may_see(db: Store, viewer: User, owner: m.Account) -> bool:
    if viewer.account_id == owner.id:
        return True
    if viewer.account_id is None:
        return viewer.role == "teacher"  # Moodle / development teachers see everyone
    if owner.role == "teacher" and viewer.role == "learner":
        return True  # students may look teachers up
    pair = (
        {"student_id": viewer.account_id, "teacher_id": owner.id}
        if viewer.role == "learner"
        else {"student_id": owner.id, "teacher_id": viewer.account_id}
    )
    return db.count(m.TeacherLink, {**pair, "status": {"$in": ["pending", "accepted"]}}) > 0


@router.get("/people/{username}/photo")
def person_photo(username: str, user: Me, db: Db) -> Response:
    owner = db.find_one(m.Account, {"username": username.lower()})
    photo = db.get(m.AccountPhoto, owner.id) if owner else None
    if owner is None or photo is None or not _may_see(db, user, owner):
        raise HTTPException(404, "No photo")
    return Response(
        photo.data,
        media_type=photo.content_type,
        headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )


class PasswordIn(BaseModel):
    current: str = Field(min_length=1, max_length=128)
    new: str = Field(min_length=1, max_length=128)


@router.post("/me/password", status_code=204)
def change_password(body: PasswordIn, request: Request, user: Me, db: Db) -> None:
    account = _account(db, user)
    if not acc.verify_password(body.current, account.password_hash):
        raise HTTPException(403, "Your current password is not right.")
    try:
        acc.check_password_rules(
            body.new, account.username, account.email, _settings(request).accounts.password_min
        )
    except AccountError as exc:
        raise HTTPException(422, str(exc)) from exc
    account.password_hash = acc.hash_password(body.new)
    account.session_version += 1
    db.commit()
    _sign_in(request, account)  # this device stays signed in; others are signed out


class DeleteIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


@router.post("/me/account/delete", status_code=204)
def delete_my_account(body: DeleteIn, request: Request, user: Me, db: Db) -> None:
    account = _account(db, user)
    if not acc.verify_password(body.password, account.password_hash):
        raise HTTPException(403, "Your password is not right.")
    acc.delete_account(db, account)
    db.commit()
    request.session.clear()


# --- students and teachers ------------------------------------------------------------------


class PersonOut(BaseModel):
    username: str
    name: str
    has_photo: bool


def _person(db: Store, account: m.Account) -> PersonOut:
    return PersonOut(
        username=account.username,
        name=account.name,
        has_photo=db.get(m.AccountPhoto, account.id) is not None,
    )


@router.get("/teachers/search")
def search_teachers(q: str, user: Learner, db: Db) -> list[PersonOut]:
    needle = q.strip().lower()
    if len(needle) < 2:
        return []
    rows = db.find(
        m.Account,
        {"role": "teacher", "username": {"$regex": f"^{re.escape(needle)}"}},
        sort=[("username", 1)],
        limit=10,
    )
    return [_person(db, a) for a in rows]


class LinkOut(BaseModel):
    id: int
    status: str
    person: PersonOut
    created_at: datetime
    decided_at: datetime | None
    learner_id: str | None = None  # teachers: opens the student's details
    email_verified: bool | None = None


class RequestIn(BaseModel):
    username: str = Field(min_length=3, max_length=30)


@router.get("/me/teachers")
def my_teachers(user: Learner, db: Db) -> list[LinkOut]:
    account = _account(db, user)
    out = []
    for link in db.find(m.TeacherLink, {"student_id": account.id}, sort=[("created_at", -1)]):
        teacher = db.get(m.Account, link.teacher_id)
        if teacher:
            out.append(
                LinkOut(
                    id=link.id,
                    status=link.status,
                    person=_person(db, teacher),
                    created_at=link.created_at,
                    decided_at=link.decided_at,
                )
            )
    return out


@router.post("/me/teachers", status_code=201)
def request_teacher(body: RequestIn, request: Request, user: Learner, db: Db) -> LinkOut:
    account = _account(db, user)
    _needs_verification(request, account)
    teacher = db.find_one(m.Account, {"username": body.username.strip().lower(), "role": "teacher"})
    if teacher is None:
        raise HTTPException(404, "No teacher has that user id.")
    return _ask(db, account, teacher)


class JoinIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)


@router.post("/me/teachers/join", status_code=201)
def join_with_code(body: JoinIn, request: Request, user: Learner, db: Db) -> LinkOut:
    """A teacher's class code finds the teacher; the teacher still accepts the request."""
    _limit(request, "login")  # codes must not be guessable by trying many
    account = _account(db, user)
    _needs_verification(request, account)
    try:
        code = acc.normalize_class_code(body.code)
    except AccountError:
        code = ""
    row = db.get(m.ClassCode, code) if code else None
    teacher = db.get(m.Account, row.teacher_id) if row else None
    if teacher is None:
        raise HTTPException(404, "No class has that code. Check it with your teacher.")
    return _ask(db, account, teacher)


def _ask(db: Store, account: m.Account, teacher: m.Account) -> LinkOut:
    link = db.find_one(m.TeacherLink, {"student_id": account.id, "teacher_id": teacher.id})
    if link and link.status == "accepted":
        raise HTTPException(409, f"{teacher.name} is already your teacher.")
    if link and link.status == "pending":
        raise HTTPException(
            409, f"You have already asked {teacher.name}. Please wait for an answer."
        )
    if link:  # declined before: ask again
        link.status, link.created_at, link.decided_at = "pending", datetime.now(UTC), None
    else:
        link = m.TeacherLink(student_id=account.id, teacher_id=teacher.id)
        db.add(link)
    db.commit()
    return LinkOut(
        id=link.id,
        status=link.status,
        person=_person(db, teacher),
        created_at=link.created_at,
        decided_at=link.decided_at,
    )


@router.delete("/me/teachers/{link_id}", status_code=204)
def leave_teacher(link_id: int, user: Learner, db: Db) -> None:
    account = _account(db, user)
    link = db.get(m.TeacherLink, link_id)
    if link is None or link.student_id != account.id:
        raise HTTPException(404, "Not found")
    db.delete(link)
    db.commit()


def _student_link(db: Store, link: m.TeacherLink) -> LinkOut | None:
    student = db.get(m.Account, link.student_id)
    if student is None:
        return None
    return LinkOut(
        id=link.id,
        status=link.status,
        person=_person(db, student),
        created_at=link.created_at,
        decided_at=link.decided_at,
        learner_id=student.learner_id,
        email_verified=student.email_verified,
    )


@router.get("/teacher/requests")
def teacher_requests(user: Teacher, db: Db) -> list[LinkOut]:
    account = _account(db, user)
    links = db.find(
        m.TeacherLink, {"teacher_id": account.id, "status": "pending"}, sort=[("created_at", 1)]
    )
    return [x for x in (_student_link(db, link) for link in links) if x]


class DecideIn(BaseModel):
    accept: bool


@router.post("/teacher/requests/{link_id}")
def decide_request(
    link_id: int, body: DecideIn, request: Request, user: Teacher, db: Db
) -> LinkOut:
    account = _account(db, user)
    link = db.get(m.TeacherLink, link_id)
    if link is None or link.teacher_id != account.id or link.status != "pending":
        raise HTTPException(404, "No such request")
    if body.accept:
        _needs_verification(request, account)
    link.status, link.decided_at = ("accepted" if body.accept else "declined"), datetime.now(UTC)
    db.commit()
    out = _student_link(db, link)
    if out is None:
        raise HTTPException(404, "No such request")
    return out


@router.get("/teacher/my-students")
def my_students(user: Teacher, db: Db) -> list[LinkOut]:
    account = _account(db, user)
    links = db.find(
        m.TeacherLink, {"teacher_id": account.id, "status": "accepted"}, sort=[("decided_at", -1)]
    )
    return [x for x in (_student_link(db, link) for link in links) if x]


@router.delete("/teacher/my-students/{link_id}", status_code=204)
def remove_student(link_id: int, user: Teacher, db: Db) -> None:
    account = _account(db, user)
    link = db.get(m.TeacherLink, link_id)
    if link is None or link.teacher_id != account.id:
        raise HTTPException(404, "Not found")
    db.delete(link)
    db.commit()


# --- a teacher's permanent class code --------------------------------------------------------


class ClassCodeOut(BaseModel):
    code: str | None


class ClassCodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)


@router.get("/teacher/class-code")
def get_class_code(user: Teacher, db: Db) -> ClassCodeOut:
    row = db.find_one(m.ClassCode, {"teacher_id": _account(db, user).id})
    return ClassCodeOut(code=row.id if row else None)


@router.put("/teacher/class-code")
def set_class_code(body: ClassCodeIn, user: Teacher, db: Db) -> ClassCodeOut:
    """Choose or change the code; the previous code stops working."""
    account = _account(db, user)
    try:
        code = acc.normalize_class_code(body.code)
    except AccountError as exc:
        raise HTTPException(422, str(exc)) from exc
    current = db.find_one(m.ClassCode, {"teacher_id": account.id})
    if current is not None and current.id == code:
        return ClassCodeOut(code=code)
    owner = db.get(m.ClassCode, code)
    if owner is not None:
        raise HTTPException(409, "Another class already uses that code. Please choose another.")
    if current is not None:
        db.delete(current)
    db.add(m.ClassCode(id=code, teacher_id=account.id))
    try:
        db.commit()
    except IntegrityError as exc:  # two saves at once
        raise HTTPException(409, "That code was just taken. Please choose another.") from exc
    return ClassCodeOut(code=code)


@router.delete("/teacher/class-code", status_code=204)
def remove_class_code(user: Teacher, db: Db) -> None:
    db.delete_many(m.ClassCode, {"teacher_id": _account(db, user).id})
    db.commit()
