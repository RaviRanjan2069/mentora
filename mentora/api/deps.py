"""Shared API dependencies: database, orchestrator, signed-cookie user session, roles."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException, Request

from mentora.db import Store, StoreFactory
from mentora.orchestrator.turn import Orchestrator

Role = Literal["learner", "teacher"]


@dataclass(frozen=True)
class User:
    id: str  # pseudonym; never a raw LMS id
    role: Role
    name: str
    via: Literal["lti", "dev", "account"]
    account_id: str | None = None  # signed in with a Mentora account
    version: int = 0  # the account's session_version when signing in


def session_factory(request: Request) -> StoreFactory:
    factory: StoreFactory = request.app.state.session_factory
    return factory


def db_session(request: Request) -> Iterator[Store]:
    with session_factory(request)() as db:
        yield db


_BUILD_LOCK = threading.Lock()


def get_orchestrator(state: Any) -> Orchestrator:
    """The app's orchestrator, built on first use (once, even under concurrent requests)."""
    if getattr(state, "orchestrator", None) is None:
        with _BUILD_LOCK:
            if getattr(state, "orchestrator", None) is None:
                from mentora.orchestrator.session import build_orchestrator

                state.orchestrator = build_orchestrator(state.settings, state.session_factory)
    orch: Orchestrator = state.orchestrator
    return orch


def orchestrator(request: Request) -> Orchestrator:
    return get_orchestrator(request.app.state)


def warm_up(state: Any) -> None:
    """Load everything a first reply needs (retrieval, reranker, NLI judge, local model).
    Runs in a background thread at server start; failures only cost the first learner time."""
    log = logging.getLogger("mentora.api")
    try:
        orch = get_orchestrator(state)
        if orch.rag is not None:
            orch.rag.search("warm up")
        orch.judge.entails("Python is a language.", "Python is a language.")
        settings = state.settings
        if settings.llm.backend == "local":
            import httpx

            native = settings.local_llm_base_url.rstrip("/").removesuffix("/v1")
            key = settings.local_llm_api_key.get_secret_value()
            httpx.post(
                f"{native}/api/generate",
                json={"model": settings.llm.local_model, "keep_alive": "60m"},
                headers={"Authorization": f"Bearer {key}"} if key else {},
                timeout=settings.llm.timeout_s,
            )
        log.info("warm-up finished")
    except Exception:
        log.warning("warm-up failed", exc_info=True)


def effective_llm_backend(state: Any) -> str:
    """The configured back-end, or "offline" while a local model is unreachable and the
    templates stand in (so the UI shows its Demo mode notice)."""
    from mentora.llm.backends.fallback import FallbackBackend

    orch = getattr(state, "orchestrator", None)
    backend = getattr(getattr(orch, "client", None), "backend", None)
    if isinstance(backend, FallbackBackend) and backend.degraded:
        return "offline"
    return str(state.settings.llm.backend)


def current_user(request: Request) -> User:
    raw = request.session.get("user")
    if not raw:
        raise HTTPException(401, "Not signed in")
    try:
        user = User(**raw)
    except TypeError:  # a cookie from an older version
        request.session.clear()
        raise HTTPException(401, "Not signed in") from None
    until = request.session.get("until")
    if isinstance(until, (int, float)) and time.time() > until:
        request.session.clear()  # "Keep me signed in" was off and the short session is over
        raise HTTPException(401, "Your session has ended. Please sign in again.")
    if user.account_id is not None:
        # A password change, reset or deleted account signs out every other device.
        from mentora.db import models as m

        with session_factory(request)() as db:
            account = db.get(m.Account, user.account_id)
        if account is None or account.session_version != user.version:
            request.session.clear()
            raise HTTPException(401, "Your session has ended. Please sign in again.")
    return user


def require_learner(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "learner":
        raise HTTPException(403, "Learners only")
    return user


def require_teacher(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "teacher":
        raise HTTPException(403, "Teachers only")
    return user


SHORT_SESSION_S = 12 * 3600  # when "Keep me signed in" is off


def sign_in(request: Request, user: User, remember: bool | None = None) -> None:
    """Stores the user in the signed session cookie. ``remember`` False ends the session after
    12 hours (the cookie itself lasts ``accounts.session_days``); None keeps the current limit."""
    until = request.session.get("until")
    request.session.clear()
    if remember is False:
        until = int(time.time()) + SHORT_SESSION_S
    elif remember is True:
        until = None
    if until is not None:
        request.session["until"] = until
    request.session["user"] = {
        "id": user.id,
        "role": user.role,
        "name": user.name,
        "via": user.via,
        "account_id": user.account_id,
        "version": user.version,
    }


def visible_learners(user: User, db: Store) -> set[str] | None:
    """Learner pseudonyms a teacher may see: an account teacher sees their accepted students;
    None (everyone) for teachers from Moodle or the development sign-in."""
    if user.account_id is None:
        return None
    from mentora.db import models as m

    student_ids = [
        sid
        for (sid,) in db.values(
            m.TeacherLink, ["student_id"], {"teacher_id": user.account_id, "status": "accepted"}
        )
    ]
    if not student_ids:
        return set()
    return {
        lid for (lid,) in db.values(m.Account, ["learner_id"], {"id": {"$in": student_ids}}) if lid
    }


def escalation_scope(user: User, db: Store) -> dict[str, Any]:
    """Filter for the escalations a teacher sees: an account teacher sees their own students'
    and those of students with no teacher yet, so a distress message always reaches someone.
    Empty (everything) for teachers from Moodle or the development sign-in."""
    mine = visible_learners(user, db)
    if mine is None:
        return {}
    from mentora.db import models as m

    linked_students = db.distinct(m.TeacherLink, "student_id", {"status": "accepted"})
    linked = {
        lid
        for (lid,) in db.values(m.Account, ["learner_id"], {"id": {"$in": linked_students}})
        if lid
    }
    return {
        "$or": [
            {"learner_id": {"$in": sorted(mine)}},
            {"learner_id": {"$nin": sorted(linked)}},
        ]
    }
