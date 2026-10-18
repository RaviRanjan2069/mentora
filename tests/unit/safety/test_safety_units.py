from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from mentora.config import get_settings
from mentora.db import StoreFactory
from mentora.db import models as m
from mentora.policy.catalogue import ESCALATE, WAIT, default_catalogue
from mentora.safety.feasibility import FilterContext, feasible_set
from mentora.safety.integrity_check import ItemView, integrity_check
from mentora.safety.teacher_rules import load_teacher_rules, parse_rule
from mentora.safety.wellbeing import detect_distress, support_message

CAT = default_catalogue()
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
GRADED_MCQ = ItemView(text="Which call prints 0..4?", graded=True, answer_key="B")
GRADED_FREE = ItemView(
    text="What does 7 // 2 give?", graded=True, answer_key="3", item_type="short"
)


def _check(text: str, item: ItemView | None) -> bool:
    return integrity_check(text, item, max_code_lines=4).ok


# --- integrity ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "The answer is B.",
        "Option B is the one you want.",
        "Pick (B) is correct.",  # "(B) is"
        "You should choose option B.",
        "Here's the full solution: use range(5).",
        "```python\nfor i in range(5):\n    x = i\n    y = x\n    z = y\n    print(z)\n```",
    ],
)
def test_integrity_flags_giveaways_on_graded_items(text: str) -> None:
    assert not _check(text, GRADED_MCQ)


def test_integrity_flags_numeric_answer() -> None:
    assert not _check("It gives 3 when you divide.", GRADED_FREE)
    assert _check("What happens to the remainder when you use //?", GRADED_FREE)
    assert _check("Try 13 // 4 first.", GRADED_FREE)  # 13 is not 3


def test_integrity_allows_socratic_guidance_and_ungraded_items() -> None:
    assert _check("Compare options A and B again: where does each one stop?", GRADED_MCQ)
    assert _check("What does range(5) start from? Compare the endpoints.", GRADED_MCQ)
    ungraded = ItemView(text="practice", graded=False, answer_key="B")
    assert _check("The answer is B.", ungraded)
    assert _check("anything", None)


@settings(max_examples=300, deadline=None)
@given(st.text(min_size=0, max_size=80), st.text(min_size=0, max_size=80))
def test_integrity_always_catches_embedded_free_text_key(prefix: str, suffix: str) -> None:
    item = ItemView(text="q", graded=True, answer_key="floor division", item_type="short")
    assert not _check(f"{prefix} floor division {suffix}", item)


# --- well-being -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "tier"),
    [
        ("honestly I want to die", "crisis"),
        ("I keep thinking about hurting myself", "crisis"),
        ("i don't want to live like this", "crisis"),
        ("I can't cope with this course anymore", "distress"),
        ("I'm so overwhelmed", "distress"),
        ("I feel completely hopeless", "distress"),
        ("I had a panic attack before the quiz", "distress"),
        ("I can\N{RIGHT SINGLE QUOTATION MARK}t cope", "distress"),
    ],
)
def test_distress_detected(text: str, tier: str) -> None:
    result = detect_distress(text)
    assert result.detected and result.tier == tier


@pytest.mark.parametrize(
    "text",
    [
        "Why does my while loop never end?",
        "This loop will kill the program if it runs forever",
        "I'm not overwhelmed, just curious",
        "Can you give me a hint?",
        "",
        None,
    ],
)
def test_no_false_alarm_on_ordinary_messages(text: str | None) -> None:
    assert not detect_distress(text).detected


def test_distress_routes_only_to_escalate_with_resources() -> None:
    result = feasible_set(
        FilterContext(now=NOW, distress=True), [], catalogue=CAT, settings=get_settings().safety
    )
    assert result.feasible == {ESCALATE} and result.show_support_resources
    msg = support_message(get_settings().safety)
    assert "14416" in msg and "teacher" in msg


# --- teacher rules ----------------------------------------------------------------------


def test_week_one_rule_blocks_peer_broker() -> None:
    rule = parse_rule(
        "no peers in week 1", {"forbid": {"agent": "PeerBroker"}, "when": {"week_lte": 1}}, CAT
    )
    safety = get_settings().safety
    week1 = feasible_set(FilterContext(now=NOW, week=1), [rule], catalogue=CAT, settings=safety)
    week2 = feasible_set(FilterContext(now=NOW, week=2), [rule], catalogue=CAT, settings=safety)
    assert not any(a.agent == "PeerBroker" for a in week1.feasible)
    assert any(a.agent == "PeerBroker" for a in week2.feasible)
    assert "teacher_rule:no peers in week 1" in week1.removed


@pytest.mark.parametrize(
    "rule",
    [
        {"forbid": {}},
        {"forbid": {"agent": "Wizard"}},
        {"forbid": {"move": "give_answer"}},
        {"forbid": {"action": "Planner.fly.Socratic"}},
        {"forbid": {"action": "ESCALATE"}},  # cannot switch off the safety valve
        {"forbid": {"agent": "Planner"}, "when": {"weekday": "monday"}},
        {"forbid": {"agent": "Planner"}, "note": "free text is not allowed"},
    ],
)
def test_malformed_rules_are_rejected(rule: dict[str, object]) -> None:
    with pytest.raises((ValueError, ValidationError, KeyError)):
        parse_rule("bad", rule, CAT)


def test_rules_load_from_db(session_factory: StoreFactory) -> None:
    with session_factory.begin() as db:
        course = m.Course(code="C1", title="c")
        db.add(course)
        db.flush()
        db.add_all(
            [
                m.TeacherRule(
                    course_id=course.id,
                    name="no directive",
                    rule={"forbid": {"style": "Directive"}},
                ),
                m.TeacherRule(
                    course_id=course.id,
                    name="off",
                    rule={"forbid": {"agent": "Monitor"}},
                    active=False,
                ),
            ]
        )
        course_id = course.id
    with session_factory() as db:
        rules = load_teacher_rules(db, course_id, CAT)
    assert [r.name for r in rules] == ["no directive"]


# --- load ---------------------------------------------------------------------------------


def test_load_limit_counts_only_the_window() -> None:
    safety = get_settings().safety  # n_max 3 per 15 min
    recent = [NOW - timedelta(minutes=m) for m in (1, 5, 14)]
    full = feasible_set(
        FilterContext(now=NOW, recent_unsolicited=recent), [], catalogue=CAT, settings=safety
    )
    assert not any(CAT.is_unsolicited(a) for a in full.feasible)
    assert WAIT in full.feasible
    older = [NOW - timedelta(minutes=m) for m in (1, 5, 16)]
    ok = feasible_set(
        FilterContext(now=NOW, recent_unsolicited=older), [], catalogue=CAT, settings=safety
    )
    assert any(CAT.is_unsolicited(a) for a in ok.feasible)
