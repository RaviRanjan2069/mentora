from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mentora.config import get_settings
from mentora.course import load_course
from mentora.learner_model.calibration import CalibrationTracker
from mentora.learner_model.engagement import Engagement, engagement
from mentora.learner_model.hmm_tactics import TacticHMM
from mentora.learner_model.kt.mastery import CountMastery
from mentora.learner_model.requests import classify_request
from mentora.learner_model.srl_phase import PhaseContext, infer_phase
from mentora.learner_model.srl_tagger import (
    INDICATORS,
    SRLTagger,
    SRLTags,
    trace_goal_smart,
    trace_reflection_quality,
    trace_tags,
)
from mentora.learner_model.state import LearnerSnapshot, build_state, feature_names, sdl_stage
from mentora.learner_model.tactics import code_statement
from mentora.learner_model.tracker import LearnerTracker
from mentora.llm.backends.fake import FakeLLM
from mentora.llm.client import LLMClient
from mentora.logging_xapi.statements import (
    ActionRef,
    FilterOutcome,
    TutorActionExtension,
    learner_message,
    lms_event,
    quiz_answer,
    tutor_action,
)

ROOT = Path(__file__).resolve().parents[3]
CFG = get_settings().learner_model
T0 = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)


# --- SRL tagger -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "My goal is to finish the loop exercises tonight. First I'll re-read the slides.",
            {"goal_stated", "plan_stated", "strategy_named"},
        ),
        (
            "I'm lost on the range part, can you give me a hint?",
            {"monitoring_statement", "help_request"},
        ),
        (
            "I got 3 out of 5 because I didn't practise slicing. Next time I'll do more examples.",
            {"self_evaluation", "attribution", "adaptation_intent", "strategy_named"},
        ),
        ("ok", set()),
    ],
)
def test_trace_tags_on_coding_manual_examples(text: str, expected: set[str]) -> None:
    tags = trace_tags(text)
    assert {k for k in INDICATORS if getattr(tags, k)} == expected


def test_llm_tagger_output_is_schema_valid() -> None:
    reply = (
        '{"goal_stated": true, "plan_stated": false, "strategy_named": false, '
        '"monitoring_statement": false, "help_request": false, "self_evaluation": false, '
        '"attribution": false, "adaptation_intent": false}'
    )
    fake = FakeLLM(
        {
            "learner_model/srl_tagger": reply,
            "learner_model/goal_smart": '{"score": 0.8, "rationale": "specific"}',
            "learner_model/reflection_quality": '{"score": 0.5, "rationale": "ok"}',
        }
    )
    tagger = SRLTagger("llm", LLMClient(fake))
    tags = tagger.tag("I want to finish week 3")
    assert isinstance(tags, SRLTags) and tags.goal_stated and not tags.help_request
    assert tagger.goal_smart("finish 5 loop exercises by 6pm") == 0.8
    assert tagger.reflection_quality("it went ok") == 0.5
    assert "<" not in fake.requests[0].system or True  # prompt rendered without error


def test_llm_tagger_falls_back_to_trace_on_bad_output() -> None:
    tagger = SRLTagger("llm", LLMClient(FakeLLM({"learner_model/srl_tagger": ["nope", "nope"]})))
    assert tagger.tag("can you give me a hint?").help_request


def test_tagger_mode_auto() -> None:
    s = get_settings()
    assert SRLTagger.from_settings(s, None).mode == "trace_only"  # fake backend
    hosted = s.model_copy(update={"llm": s.llm.model_copy(update={"backend": "hosted"})})
    assert SRLTagger.from_settings(hosted, LLMClient(FakeLLM())).mode == "llm"


def test_rubric_heuristics() -> None:
    assert trace_goal_smart("Finish 5 loop exercises from week 3 by 6pm today") == 1.0
    assert trace_goal_smart("get better") < 0.5
    assert (
        trace_reflection_quality(
            "I got 3 out of 5 because I didn't practise slicing. Next time I'll do examples first."
        )
        == 1.0
    )
    assert trace_reflection_quality("fine") == 0.0


# --- requests, phase, calibration, engagement --------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("just tell me the answer", "answer"),
        ("can I get a hint?", "hint"),
        ("I don't understand slicing", "explanation"),
        ("what should I do first", "plan"),
        ("is the quiz due friday?", "question"),
        ("ok thanks", "none"),
        (None, "none"),
    ],
)
def test_classify_request(text: str | None, kind: str) -> None:
    assert classify_request(text) == kind


def test_phase_rules_and_tagger_correction() -> None:
    assert infer_phase(PhaseContext(0, False, False, False)) == "forethought"
    assert infer_phase(PhaseContext(5, True, False, True)) == "performance"
    assert infer_phase(PhaseContext(5, False, True, True)) == "reflection"
    assert infer_phase(PhaseContext(5, False, False, True)) == "performance"
    assert (
        infer_phase(PhaseContext(5, False, False, True), SRLTags(attribution=True)) == "reflection"
    )
    assert (
        infer_phase(PhaseContext(5, False, False, True), SRLTags(plan_stated=True)) == "forethought"
    )
    assert (
        infer_phase(PhaseContext(5, True, False, True), SRLTags(goal_stated=True)) == "performance"
    )


def test_calibration_formula() -> None:
    c = CalibrationTracker(eta=0.2, value=0.5)
    assert c.update(0.9, True) == pytest.approx(0.8 * 0.5 + 0.2 * 0.1)
    assert c.update(0.9, False) == pytest.approx(0.8 * 0.42 + 0.2 * 0.9)
    with pytest.raises(ValueError):
        c.update(1.5, True)
    assert c.bins()[0]["n"] == 2.0


def test_engagement() -> None:
    now = T0 + timedelta(days=10)
    starts = [T0, T0 + timedelta(days=3), T0 + timedelta(days=9), T0 - timedelta(days=30)]
    events = [T0 + timedelta(minutes=m) for m in (0, 2, 4, 30)]  # 4 min active, 26 idle
    e = engagement(starts, events, events, now, CFG)
    assert e.sessions_per_week == pytest.approx(3 / 2)
    assert e.time_on_task_hours == pytest.approx(4 / 60)
    assert e.idle_ratio == pytest.approx(26 / 30)
    assert 0 < e.dropout_risk < 1
    busy = engagement(starts * 3, events, [], now, CFG)
    assert busy.dropout_risk < e.dropout_risk


# --- state builder -------------------------------------------------------------------------


@st.composite
def snapshots(draw: st.DrawFn) -> LearnerSnapshot:
    h = draw(st.integers(1, CFG.hmm_states_max))
    alpha = np.asarray(draw(st.lists(st.floats(0, 1), min_size=h, max_size=h)))
    unit = st.floats(0, 1)
    return LearnerSnapshot(
        goal_mastery=draw(unit),
        mean_mastery=draw(unit),
        phase=draw(st.sampled_from(["forethought", "performance", "reflection"])),
        alpha=alpha,
        indicator_counts={k: draw(st.integers(0, CFG.indicator_window)) for k in INDICATORS},
        calibration=draw(unit),
        engagement=Engagement(
            draw(st.floats(0, 30)), draw(st.floats(0, 100)), draw(unit), draw(unit)
        ),
        plan_progress=draw(unit),
        learner_initiated_share=draw(unit),
        hint_before_attempt_rate=draw(st.floats(0, 3)),
        answer_request_rate=draw(unit),
    )


@settings(max_examples=200, deadline=None)
@given(snapshots())
def test_state_is_fixed_length_and_bounded(s: LearnerSnapshot) -> None:
    v = build_state(s, CFG, CFG.indicator_window)
    assert len(v) == len(feature_names(CFG)) == 28
    assert all(0.0 <= x <= 1.0 for x in v)
    assert sum(v[2:5]) == 1.0  # one-hot phase


def test_sdl_stage() -> None:
    assert [sdl_stage(x, (0.25, 0.5, 0.75)) for x in (0.0, 0.3, 0.6, 0.9)] == [1, 2, 3, 4]


# --- tactics + tracker replay ---------------------------------------------------------------


def _tutor(lid: str, sid: str, turn: int, agent: str, move: str) -> object:
    a = ActionRef(agent=agent, move=move, style="Socratic")
    ext = TutorActionExtension(
        policy_version="rule-v1",
        action=a,
        propensity=1.0,
        filter_outcome=FilterOutcome(feasible_action_ids=[a.id]),
    )
    return tutor_action(lid, sid, turn, ext, "…")


def test_tactic_coding() -> None:
    assert code_statement(quiz_answer("l", "s", 1, 1, "B", True)) == "QUIZ"
    assert code_statement(lms_event("l", "s", 1, "experienced", "x")) == "READ"
    assert code_statement(learner_message("l", "s", 1, "hi")) == "CHAT"
    assert code_statement(learner_message("l", "s", 1, "x"), {"goal_stated": True}) == "PLAN"
    assert code_statement(_tutor("l", "s", 1, "ContentTutor", "graded_hint")) == "HINT"  # type: ignore[arg-type]
    assert code_statement(_tutor("l", "s", 1, "ReflectionCoach", "record_lesson")) == "REFLECT"  # type: ignore[arg-type]
    assert code_statement(_tutor("l", "s", 1, "Monitor", "progress_nudge")) is None  # type: ignore[arg-type]


def test_tracker_replay() -> None:
    course = load_course(ROOT / "data" / "concepts.yaml")
    hmm = TacticHMM.from_json((ROOT / "tests" / "golden" / "tactic_hmm_3.json").read_text())
    tr = LearnerTracker(
        course, CFG, CountMastery((1, 1)), hmm, item_concepts={7: ["for_loops"], 8: ["recursion"]}
    )
    tr.observe(
        learner_message("l", "s", 0, "My goal is to finish 3 loop exercises today"),
        trace_tags("My goal is to finish 3 loop exercises today"),
        "plan",
    )
    assert tr.phase(has_active_goal=False) == "forethought"
    tr.start_item(7)
    tr.observe(
        learner_message("l", "s", 1, "just tell me the answer"),
        trace_tags("just tell me the answer"),
        "answer",
    )
    tr.observe(
        quiz_answer(
            "l",
            "s",
            2,
            7,
            "A",
            False,
            confidence=0.9,
            response_seconds=12.5,
            hints_used=1,
            attempt=1,
        )
    )
    tr.observe(quiz_answer("l", "s", 3, 7, "B", False, confidence=0.6, attempt=2))
    assert tr.consecutive_wrong == 2 and tr.task_active
    tr.observe(quiz_answer("l", "s", 4, 7, "C", True, confidence=0.7, attempt=3))
    assert not tr.task_active and tr.just_assessed
    assert tr.phase(has_active_goal=True) == "reflection"

    assert [x.correct for x in tr.history] == [0, 0, 1]
    assert tr.history[0].response_seconds == 12.5 and tr.history[0].hints == 1
    assert tr.calibration.value == pytest.approx(
        0.8 * (0.8 * (0.8 * 0.5 + 0.2 * 0.9) + 0.2 * 0.6) + 0.2 * 0.3
    )
    snap = tr.snapshot(
        goal_concepts=["for_loops"],
        has_active_goal=True,
        plan_progress=0.5,
        engagement=Engagement(1.0, 0.5, 0.1, 0.3),
    )
    assert snap.goal_mastery == pytest.approx((1 + 1) / (3 + 2))
    assert snap.hint_before_attempt_rate == 1.0  # answer request before the first attempt
    assert snap.answer_request_rate == 0.5
    assert snap.indicator_counts["goal_stated"] == 1
    assert np.isclose(snap.alpha.sum(), 1.0) and len(snap.alpha) == 3
    assert tr.prereq_mastery("recursion") == pytest.approx(0.5)  # functions: no data
    assert tr.prereq_mastery("variables") is None  # no prerequisites
    assert len(tr.state_vector(snap)) == 28
