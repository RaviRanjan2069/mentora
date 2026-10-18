from __future__ import annotations

from pathlib import Path

import pytest

from mentora.llm.prompts import default_registry
from mentora.logging_xapi.statements import ActionRef
from mentora.policy.catalogue import AGENTS, ESCALATE, WAIT, default_catalogue

GOLDEN = Path(__file__).resolve().parents[2] / "golden" / "catalogue_v1.txt"


def test_catalogue_v1_is_frozen() -> None:
    """Changing the catalogue invalidates logged data and trained policies: bump the version."""
    cat = default_catalogue()
    assert cat.version == "v1"
    assert [a.id for a in cat] == GOLDEN.read_text(encoding="utf-8").split()


def test_size_and_special_actions() -> None:
    cat = default_catalogue()
    assert len(cat) == 42  # 40 agent actions + WAIT + ESCALATE
    assert WAIT in cat and ESCALATE in cat
    assert {a.agent for a in cat if a.agent} == set(AGENTS)


def test_question_only_moves_are_socratic_only() -> None:
    cat = default_catalogue()
    for move in (
        "elicit_smart_goal",
        "socratic_reflection",
        "attribution_question",
        "confidence_check",
    ):
        assert cat.moves[move].styles == ["Socratic"]


def test_rag_and_unsolicited_flags() -> None:
    cat = default_catalogue()
    rag = {m for m, s in cat.moves.items() if s.needs_rag}
    assert rag == {"graded_hint", "worked_example", "concept_explanation", "textbook_link"}
    unsolicited = {m for m, s in cat.moves.items() if s.unsolicited}
    assert {"progress_nudge", "break_suggestion", "suggest_partner"} <= unsolicited
    assert not cat.is_unsolicited(WAIT) and not cat.is_unsolicited(ESCALATE)


def test_every_action_has_prompt_parts_and_why_line() -> None:
    cat = default_catalogue()
    reg = default_registry()
    for action in cat:
        if action in (WAIT, ESCALATE):
            assert cat.why_line(action) is None
            continue
        reg.fragment(f"agents/moves/{action.move}")
        reg.fragment(f"agents/roles/{action.agent}")
        reg.fragment(f"agents/styles/{action.style}")
        why = cat.why_line(action)
        assert why is not None and why.startswith("Why this suggestion:")


def test_lookup() -> None:
    cat = default_catalogue()
    a = cat.get("ContentTutor.graded_hint.Socratic")
    assert a == ActionRef(agent="ContentTutor", move="graded_hint", style="Socratic")
    with pytest.raises(KeyError):
        cat.get("ContentTutor.graded_hint.Shouty")
