"""Shared API dependencies: database, orchestrator, signed-cookie user session, roles."""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from mentora.orchestrator.turn import Orchestrator

Role = Literal["learner", "teacher"]


@dataclass(frozen=True)
class User:
    id: str  # pseudonym; never a raw LMS id
    role: Role
    name: str
    via: Literal["lti", "dev"]


def session_factory(request: Request) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    return factory


def db_session(request: Request) -> Iterator[Session]:
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


def current_user(request: Request) -> User:
    raw = request.session.get("user")
    if not raw:
        raise HTTPException(401, "Not signed in")
    return User(**raw)


def require_learner(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "learner":
        raise HTTPException(403, "Learners only")
    return user


def require_teacher(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "teacher":
        raise HTTPException(403, "Teachers only")
    return user


def sign_in(request: Request, user: User) -> None:
    request.session.clear()
    request.session["user"] = {"id": user.id, "role": user.role, "name": user.name, "via": user.via}
