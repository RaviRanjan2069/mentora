from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mentora.config import Settings, get_settings
from mentora.course import load_course, load_items, upsert_course, upsert_items
from mentora.db import StoreFactory
from mentora.llm.backends.fake import FakeLLM
from mentora.llm.client import LLMClient
from mentora.llm.types import LLMRequest
from mentora.memory.service import MemoryService
from mentora.orchestrator.turn import Orchestrator
from mentora.rag import build_pipeline
from mentora.rag.embeddings import HashingEmbedder
from mentora.rag.ingest import build_passages, embed_passages, load_documents, store_passages

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "data" / "sample" / "sessions" / "demo_session.yaml"


class Clock:
    """Deterministic clock: every reading advances 20 seconds."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=20)
        return self.now


def tutor_reply(req: LLMRequest) -> str:
    """Safe, grounded-by-construction fake reply: a question, never a claim or an answer."""
    if req.prompt_id.startswith("rag/answer"):
        return "Let's look at the course notes on this together. What do you notice first?"
    return "What do you think the next step is?"


@pytest.fixture
def seeded_course(session_factory: StoreFactory) -> int:
    course = load_course(ROOT / "data" / "concepts.yaml")
    with session_factory.begin() as db:
        course_id = upsert_course(db, course).id
        upsert_items(db, course_id, load_items(ROOT / "data" / "sample" / "items.yaml"))
    drafts = build_passages(load_documents(ROOT / "data" / "sample" / "corpus"), course, 300, 40)
    store_passages(session_factory, course_id, embed_passages(drafts, HashingEmbedder(384)))
    return course_id


MakeOrch = Callable[..., Orchestrator]


@pytest.fixture
def make_orch(session_factory: StoreFactory, seeded_course: int) -> MakeOrch:
    def make(
        settings: Settings | None = None,
        fake: FakeLLM | None = None,
        memory: MemoryService | None = None,
        start: datetime = datetime(2026, 9, 9, 10, 0, tzinfo=UTC),  # course week 1
    ) -> Orchestrator:
        s = settings or get_settings()
        course = load_course(ROOT / "data" / "concepts.yaml")
        rag = build_pipeline(s, session_factory, seeded_course)
        return Orchestrator(
            s,
            session_factory,
            client=LLMClient(fake or FakeLLM(default=tutor_reply)),
            course=course,
            rag=rag,
            memory=memory,
            clock=Clock(start),
        )

    return make


def with_mode(
    policy_mode: str = "collect",
    app_mode: str = "adaptive",
    explore_on_requests: bool = False,
    answer_mode: str = "open",
) -> Settings:
    s = get_settings()
    policy = {"mode": policy_mode, "explore_on_requests": explore_on_requests}
    return s.model_copy(
        update={
            "rag": s.rag.model_copy(update={"answer_mode": answer_mode}),
            "policy": s.policy.model_copy(update=policy),
            "app": s.app.model_copy(update={"mode": app_mode}),
        }
    )
