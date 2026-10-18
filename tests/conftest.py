from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest

from mentora.config import get_settings
from mentora.db import StoreFactory, connect
from mentora.db import models as m
from mentora.db.client import drop_mock


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("MENTORA_LLM__BACKEND", "fake")
    # Offline stand-ins for the ML models (tests never download anything).
    monkeypatch.setenv("MENTORA_RAG__EMBEDDER", "hashing")
    monkeypatch.setenv("MENTORA_RAG__RERANKER", "lexical")
    monkeypatch.setenv("MENTORA_RAG__GROUNDING_JUDGE", "lexical")
    # In-memory MongoDB, so nothing ever touches a real server.
    monkeypatch.setenv("MENTORA_DATABASE_URL", "mongomock://settings_default")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db_url() -> Iterator[str]:
    """A fresh in-memory MongoDB for one test."""
    url = f"mongomock://t_{uuid4().hex[:12]}"
    yield url
    drop_mock(url)


@pytest.fixture
def session_factory(db_url: str) -> StoreFactory:
    return connect(db_url)


@pytest.fixture
def seeded(session_factory: StoreFactory) -> dict[str, str | int]:
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
