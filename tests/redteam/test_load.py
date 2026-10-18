"""Load smoke test: concurrent learners through the real HTTP API, no errors."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from mentora.api.main import create_app
from mentora.config import get_settings
from mentora.course import load_course
from mentora.db import connect
from mentora.db.client import drop_mock
from mentora.llm.backends.fake import FakeLLM
from mentora.llm.client import LLMClient
from mentora.loadtest import run_load
from mentora.orchestrator.turn import Orchestrator
from mentora.rag import build_pipeline
from tests.unit.orchestrator.conftest import ROOT, Clock, tutor_reply


def test_concurrent_learners(tmp_path: Path) -> None:
    from mentora.offline.simulator import seed_course

    url = "mongomock://load_test"
    drop_mock(url)
    factory = connect(url)
    course_id = seed_course(factory, load_course(ROOT / "data" / "concepts.yaml"))
    settings = get_settings()
    app = create_app(settings, factory)
    app.state.orchestrator = Orchestrator(
        settings,
        factory,
        client=LLMClient(FakeLLM(default=tutor_reply)),
        course=load_course(ROOT / "data" / "concepts.yaml"),
        rag=build_pipeline(settings, factory, course_id),
        clock=Clock(datetime(2026, 9, 9, 10, tzinfo=UTC)),
    )
    result = run_load(lambda: TestClient(app), learners=12, messages=2, workers=6)
    summary = result.summary()
    print(summary)
    assert result.errors == []
    assert summary["requests"] == 12 * (5 + 2 * 3)
