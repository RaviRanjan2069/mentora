from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from mentora.config import get_settings


def make_engine(url: str | None = None, **kwargs: Any) -> Engine:
    url = url or get_settings().database_url
    if not url.startswith("sqlite"):
        # Serverless Postgres (e.g. Neon) drops idle connections when it scales to zero.
        kwargs.setdefault("pool_pre_ping", True)
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_fks(dbapi_conn: Any, _record: Any) -> None:
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


_factory: sessionmaker[Session] | None = None


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session bound to the configured database."""
    global _factory
    if _factory is None:
        _factory = make_session_factory(make_engine())
    with _factory() as session:
        yield session
