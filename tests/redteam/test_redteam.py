"""M9 'done when': the adversarial suite shows no integrity or safety failure."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mentora import redteam
from mentora.db import models as m
from mentora.llm.backends.fake import FakeLLM
from mentora.orchestrator.turn import Orchestrator
from tests.unit.orchestrator.conftest import MakeOrch, make_orch, seeded_course, with_mode

__all__ = ["make_orch", "seeded_course"]


@pytest.fixture
def suite(
    make_orch: MakeOrch, session_factory: sessionmaker[Session]
) -> list[redteam.ScenarioResult]:
    with session_factory() as db:
        keys = [k for k in db.scalars(select(m.Item.answer_key)) if k]

    def make(fake: FakeLLM) -> Orchestrator:
        return make_orch(with_mode("collect"), fake=fake)

    return redteam.run_suite(make, session_factory, keys)


def test_adversarial_suite_has_no_failures(suite: list[redteam.ScenarioResult]) -> None:
    report = redteam.report_markdown(suite)
    print(report)
    assert [r.name for r in suite] == [
        "graded-answer requests",
        "prompt injection via messages",
        "prompt injection via course files",
        "distress",
        "off-topic questions",
        "very long session (200 turns)",
    ]
    for r in suite:
        assert r.attempts > 0, r.name
        assert r.passed, f"{r.name}: {r.failures}"


def test_suite_detects_a_broken_safety_layer(
    make_orch: MakeOrch, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutation check: with the output integrity check and distress detection switched off,
    the suite must report failures (otherwise a green run would mean nothing)."""
    from mentora.agents import base
    from mentora.orchestrator import turn
    from mentora.safety.integrity_check import IntegrityResult
    from mentora.safety.wellbeing import DistressResult

    monkeypatch.setattr(base, "integrity_check", lambda *a, **k: IntegrityResult(True))
    monkeypatch.setattr(turn, "detect_distress", lambda text: DistressResult(False))
    with session_factory() as db:
        keys = [k for k in db.scalars(select(m.Item.answer_key)) if k]
    orch = make_orch(with_mode("collect"), fake=redteam.leaky_llm(keys))
    assert not redteam.graded_answer_requests(orch, session_factory).passed
    assert not redteam.distress(orch, session_factory).passed
