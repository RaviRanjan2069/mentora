"""Who am I, sign-out, and a development sign-in (off in production)."""

from __future__ import annotations

import hmac
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from mentora.api.deps import User, current_user, effective_llm_backend, sign_in
from mentora.config.settings import Settings
from mentora.db import models as m
from mentora.privacy import pseudonymize

router = APIRouter(prefix="/api", tags=["auth"])


class MeOut(BaseModel):
    id: str
    role: str
    name: str
    via: str
    llm_backend: str
    mode: str
    # Signed in with a Mentora account:
    username: str | None = None
    email_verified: bool | None = None
    has_photo: bool = False
    photo_version: int = 0


class DevLoginIn(BaseModel):
    role: Literal["learner", "teacher"]
    name: str = Field(min_length=1, max_length=60)
    access_code: str = Field(default="", max_length=200)


@router.get("/me")
def me(request: Request, user: Annotated[User, Depends(current_user)]) -> MeOut:
    s: Settings = request.app.state.settings
    out = MeOut(
        id=user.id,
        role=user.role,
        name=user.name,
        via=user.via,
        llm_backend=effective_llm_backend(request.app.state),
        mode=s.app.mode,
    )
    if user.account_id is not None:
        with request.app.state.session_factory() as db:
            account = db.get(m.Account, user.account_id)
            photo = db.get(m.AccountPhoto, user.account_id)
        if account is not None:
            out.username, out.email_verified = account.username, account.email_verified
            out.has_photo = photo is not None
            out.photo_version = int(photo.updated_at.timestamp()) if photo else 0
    return out


@router.post("/dev/login")
def dev_login(body: DevLoginIn, request: Request) -> MeOut:
    s: Settings = request.app.state.settings
    if not s.dev_login:
        raise HTTPException(404, "Not found")
    code = s.dev_teacher_code.get_secret_value()
    if (
        body.role == "teacher"
        and code
        and not hmac.compare_digest(body.access_code.encode(), code.encode())
    ):
        raise HTTPException(403, "Teacher sign-in needs the demo access code")
    user_id = pseudonymize(
        f"dev|{body.role}|{body.name.strip().lower()}", s.pseudonym_salt.get_secret_value()
    )
    if body.role == "learner":
        with request.app.state.session_factory.begin() as db:
            if db.get(m.Learner, user_id) is None:
                db.add(m.Learner(id=user_id))
    user = User(user_id, body.role, body.name.strip(), "dev")
    sign_in(request, user)
    return MeOut(
        id=user.id,
        role=user.role,
        name=user.name,
        via=user.via,
        llm_backend=effective_llm_backend(request.app.state),
        mode=s.app.mode,
    )


@router.post("/logout", status_code=204)
def logout(request: Request) -> None:
    request.session.clear()
