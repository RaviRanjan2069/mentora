from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from mentora import __version__
from mentora.api import lti
from mentora.api.routes import auth, console, health, learner, rag, teacher
from mentora.config import Settings, get_settings
from mentora.db import StoreFactory, connect, ensure_schema

STATIC_DIR = Path(__file__).with_name("static")
# The web app is plain HTML, CSS and JavaScript (ES modules), served as is: no build step.
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


class AppFiles(StaticFiles):
    """Web app files keep their names across deploys (nothing is fingerprinted), so browsers
    must revalidate them (cheap, by ETag) instead of running stale scripts."""

    def file_response(
        self, full_path: Any, stat_result: Any, scope: Any, status_code: int = 200
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(
    settings: Settings | None = None, session_factory: StoreFactory | None = None
) -> FastAPI:
    settings = settings or get_settings()
    own_database = session_factory is None
    if session_factory is None:
        # Connecting is lazy; nothing touches the database until the server starts.
        session_factory = connect(settings.database_url, create_schema=False)
    factory = session_factory

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if own_database:
            ensure_schema(factory.database)  # indexes (idempotent)
        yield

    app = FastAPI(
        title=settings.app.name,
        version=__version__,
        description="Mentora: a Self-Learning Strategy Agent for self-regulated learning.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.orchestrator = None
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret.get_secret_value(),
        session_cookie="mentora_session",
        same_site=settings.cookie_samesite,
        https_only=settings.cookie_https_only,
        max_age=8 * 3600,
    )
    for router in (
        health.router,
        rag.router,
        auth.router,
        learner.router,
        teacher.router,
        console.router,
        lti.router,
    ):
        app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.mount("/app", AppFiles(directory=FRONTEND_DIR, html=True), name="app")

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse("/app/")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")

    return app


def _start_warm_up(application: FastAPI) -> None:
    import threading

    from mentora.api.deps import warm_up

    threading.Thread(
        target=warm_up, args=(application.state,), name="mentora-warm-up", daemon=True
    ).start()


app = create_app()
_start_warm_up(app)  # only the served app warms up; apps built in tests stay lazy
