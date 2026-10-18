from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from mentora.config import get_settings
from mentora.db import Base, make_engine, make_session_factory
from mentora.db import models as m


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("MENTORA_LLM__BACKEND", "fake")
    # Offline stand-ins for the ML models (tests never download anything).
    monkeypatch.setenv("MENTORA_RAG__EMBEDDER", "hashing")
    monkeypatch.setenv("MENTORA_RAG__RERANKER", "lexical")
    monkeypatch.setenv("MENTORA_RAG__GROUNDING_JUDGE", "lexical")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = make_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine)


@pytest.fixture
def seeded(session_factory: sessionmaker[Session]) -> dict[str, str | int]:
    """One synthetic learner, course and session."""
    with session_factory.begin() as db:
        course = m.Course(code="SYN101", title="Synthetic Intro Course")
        learner = m.Learner(id="lrn_test0001")
        db.add_all([course, learner])
        db.flush()
        sess = m.Session(learner_id=learner.id, course_id=course.id, policy_version="rule-v1")
        db.add(sess)
        db.flush()
        return {"learner_id": learner.id, "course_id": course.id, "session_id": sess.id}
