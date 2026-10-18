from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mentora.agents import TurnContext, TutorTeam
from mentora.config import Settings, get_settings
from mentora.llm.backends.fake import FakeLLM
from mentora.llm.client import LLMClient
from mentora.llm.types import LLMRequest
from mentora.policy.catalogue import Catalogue, default_catalogue
from mentora.rag.grounding import LexicalEntailmentJudge
from mentora.rag.retrieve import Passage
from mentora.safety.feasibility import FilterContext, FilterResult, feasible_set
from mentora.safety.integrity_check import ItemView

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
PASSAGES = (
    Passage(
        "syn101-week3-loops-p002",
        "The range function produces a sequence of integers. range(5) gives 0, 1, 2, 3 and 4.",
        "For loops and ranges",
        3,
        ("for_loops",),
    ),
    Passage(
        "syn101-faq-q3-p001",
        "Q: Does range(10) include 10? A: No. range(10) stops before 10.",
        "FAQ",
        3,
        ("for_loops",),
    ),
)


def golden_reply(req: LLMRequest) -> str:
    """Deterministic tutor reply: a question (never a factual claim), tagged with the action."""
    action = req.prompt_id.split(":", 1)[1]
    return f"({action}) What do you think the next step is?"


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def catalogue() -> Catalogue:
    return default_catalogue()


def make_team(fake: FakeLLM, settings: Settings, catalogue: Catalogue) -> TutorTeam:
    return TutorTeam(
        LLMClient(fake),
        catalogue=catalogue,
        settings=settings,
        judge=LexicalEntailmentJudge(settings.rag.lexical_entailment_threshold),
    )


def open_filter(catalogue: Catalogue, settings: Settings) -> FilterResult:
    """Everything allowed (no constraint active)."""
    return feasible_set(FilterContext(now=NOW), [], catalogue=catalogue, settings=settings.safety)


@pytest.fixture
def ctx() -> TurnContext:
    return TurnContext(
        course_title="Introduction to Programming (synthetic)",
        phase="performance",
        state_summary="Mastery of for_loops 0.42; plan step 2 of 3; confidence calibration fair.",
        learner_message="I don't get why range(10) doesn't print 10.",
        memory_items=("Prefers short examples.",),
        passages=PASSAGES,
        item=ItemView(
            text="What is the last number printed by: for i in range(10): print(i)",
            graded=False,
            answer_key="9",
            item_type="short",
        ),
        target_concept="For loops and ranges",
        goals=("Finish the week 3 loop exercises today",),
    )
