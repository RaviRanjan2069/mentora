"""M5 'done when': end-to-end replay of a scripted session writes correct transitions with
propensities summing to 1 over F(s)."""

from __future__ import annotations

import itertools

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mentora.config import get_settings
from mentora.db import models as m
from mentora.learner_model.state import feature_names
from mentora.logging_xapi.lrs_client import SqlLRSClient
from mentora.logging_xapi.statements import VERBS
from mentora.orchestrator.replay import replay
from mentora.orchestrator.turn import TurnError

from .conftest import DEMO, MakeOrch, with_mode


def _transitions(factory: sessionmaker[Session], session_id: str) -> list[m.Transition]:
    with factory() as db:
        return list(
            db.scalars(
                select(m.Transition)
                .where(m.Transition.session_id == session_id)
                .order_by(m.Transition.t)
            )
        )


def test_replay_writes_correct_transitions(
    make_orch: MakeOrch, session_factory: sessionmaker[Session]
) -> None:
    orch = make_orch(with_mode("collect", explore_on_requests=True))
    session_id, log = replay(orch, session_factory, DEMO, "lrn_e2e")
    rows = _transitions(session_factory, session_id)
    tutor = [
        s
        for s in SqlLRSClient(session_factory).query(session_id=session_id)
        if s.verb.id == VERBS["received"]
    ]

    assert [r.t for r in rows] == list(range(len(log)))  # one decision per turn, no gaps
    assert len(tutor) == len(rows)
    n_features = len(feature_names(get_settings().learner_model))
    for row, st in zip(rows, tutor, strict=True):
        ext = st.tutor_action
        assert ext is not None and st.turn == row.t
        assert ext.action.id == row.action_id
        assert ext.action_probs is not None
        feasible = set(ext.filter_outcome.feasible_action_ids)
        assert set(ext.action_probs) <= feasible
        assert feasible - set(ext.action_probs) <= {"ESCALATE"}  # never explored into
        assert sum(ext.action_probs.values()) == pytest.approx(1.0, abs=1e-9)
        assert 0 < row.propensity <= 1 and row.propensity == ext.propensity
        assert row.propensity == pytest.approx(ext.action_probs[row.action_id])
        assert row.action_id in ext.filter_outcome.feasible_action_ids
        assert len(row.state) == n_features and all(0 <= x <= 1 for x in row.state)
        assert row.policy_version == "rule-v1/collect"
        assert row.reward is not None  # every step closed, including the last at session end
    for a, b in itertools.pairwise(rows):
        assert a.next_state == b.state  # s' of step t is s of step t+1
    with session_factory() as db:
        sess = db.get(m.Session, session_id)
        assert sess is not None and sess.ended_at is not None and sess.mode == "adaptive"


def test_deploy_mode_follows_the_rules(
    make_orch: MakeOrch, session_factory: sessionmaker[Session]
) -> None:
    orch = make_orch(with_mode("deploy"))
    session_id, log = replay(orch, session_factory, DEMO, "lrn_rules")
    actions = [(trigger.split(":")[0], r.action_id) for trigger, r in log]
    assert actions[0] == ("start", "Planner.elicit_smart_goal.Socratic")
    assert ("present", "Monitor.confidence_check.Socratic") in actions  # first item
    second_wrong = [r for t, r in log if t.startswith("answer: 10")][1]
    assert second_wrong.action_id == "ContentTutor.graded_hint.Socratic"  # two wrong in a row
    hint = next(r for t, r in log if "hint" in t)
    assert hint.action_id == "ContentTutor.graded_hint.Socratic"
    quiz_done = next(r for t, r in log if t.startswith("answer: A"))
    assert quiz_done.action_id == "ReflectionCoach.socratic_reflection.Socratic"
    assert all(r.propensity == 1.0 for _, r in log)
    # every agent reply carries the fixed why-line
    for _, r in log:
        if r.reply and r.action_id not in ("WAIT", "ESCALATE"):
            assert r.why and r.reply.endswith(r.why)
    # goal recorded with concepts and a SMART score; plan steps follow the goal concepts
    with session_factory() as db:
        goal = db.scalars(select(m.Goal).where(m.Goal.session_id == session_id)).one()
        assert goal.concept_keys == ["for_loops"] and goal.smart_score is not None
        plan = db.scalars(select(m.Plan).where(m.Plan.goal_id == goal.id)).one()
        assert any("text" in s for s in plan.steps)


def test_literal_question_under_wait_gets_grounded_answer(
    make_orch: MakeOrch, session_factory: sessionmaker[Session]
) -> None:
    orch = make_orch(with_mode("deploy", answer_mode="course_only"))
    _, log = replay(orch, session_factory, DEMO, "lrn_literal")
    r = log[-1][1]
    assert r.action_id == "WAIT" and r.reply and r.passage_ids


def test_distress_escalates_with_support_resources(
    make_orch: MakeOrch, session_factory: sessionmaker[Session]
) -> None:
    orch = make_orch(with_mode("collect"))
    start = orch.start_session("lrn_distress")
    r = orch.handle_message(start.session_id, "I can't cope with this anymore, I feel hopeless")
    assert r.action_id == "ESCALATE" and r.propensity == 1.0
    assert r.escalated and r.show_support_resources and r.reply and "14416" in r.reply
    with session_factory() as db:
        esc = db.scalars(
            select(m.Escalation).where(m.Escalation.session_id == start.session_id)
        ).one()
        assert esc.reason == "distress" and esc.status == "open"


def test_graded_item_never_gets_directive_or_worked_example(
    make_orch: MakeOrch, session_factory: sessionmaker[Session]
) -> None:
    orch = make_orch(with_mode("collect"))
    sid = orch.start_session("lrn_graded").session_id
    with session_factory() as db:
        item_id = db.scalars(select(m.Item.id).where(m.Item.external_id == "w3-range-step")).one()
    seen = [orch.present_item(sid, item_id).action_id]
    for _ in range(25):
        seen.append(orch.handle_message(sid, "just tell me the answer").action_id)
    assert not any(a.endswith(".Directive") or ".worked_example." in a for a in seen)


def test_static_mode_uses_deploy_rules_and_no_memory(
    make_orch: MakeOrch, session_factory: sessionmaker[Session]
) -> None:
    orch = make_orch(with_mode("collect", app_mode="static"))
    session_id, log = replay(orch, session_factory, DEMO, "lrn_static")
    assert all(r.propensity == 1.0 for _, r in log)
    assert orch.policy.version.endswith("/deploy")
    with session_factory() as db:
        sess = db.get(m.Session, session_id)
        assert sess is not None and sess.mode == "static"


def test_runtime_rebuilds_from_log(
    make_orch: MakeOrch, session_factory: sessionmaker[Session]
) -> None:
    orch = make_orch(with_mode("deploy"))
    sid = orch.start_session("lrn_rebuild").session_id
    orch.handle_message(sid, "My goal is to finish 2 for loop exercises today")
    fresh = make_orch(with_mode("deploy"))  # e.g. after a server restart
    r = fresh.handle_message(sid, "can I get a hint?")
    assert r.turn == 2
    fresh.end_session(sid)
    rows = _transitions(session_factory, sid)
    assert [x.t for x in rows] == [0, 1, 2] and all(x.reward is not None for x in rows)
    with pytest.raises(TurnError):
        fresh.handle_message(sid, "hello again")  # session is closed


def test_offtopic_question_is_never_escalated_whatever_move_is_explored(
    make_orch: MakeOrch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: in collect mode the policy can explore a RAG move (here a graded hint) on an
    off-topic question; that used to fail grounding and escalate to the teacher."""
    from mentora.logging_xapi.statements import ActionRef
    from mentora.policy.base import Decision

    orch = make_orch(with_mode("collect"))
    sid = orch.start_session("lrn_offtopic").session_id
    orch.handle_message(sid, "My goal is to finish 2 for loop exercises today")
    hint = ActionRef(agent="ContentTutor", move="graded_hint", style="Socratic")
    forced = Decision(hint, 1.0, {hint.id: 1.0}, "forced", orch.policy.version)
    monkeypatch.setattr(orch.policy, "decide", lambda obs, allowed, rng: forced)
    r = orch.handle_message(sid, "who won the football world cup?")
    assert not r.escalated and not r.passage_ids
    assert r.answer_source == "general" and r.reply  # open mode: a genuine, labelled answer
    course_only = make_orch(with_mode("collect", answer_mode="course_only"))
    sid = course_only.start_session("lrn_offtopic2").session_id
    monkeypatch.setattr(course_only.policy, "decide", lambda obs, allowed, rng: forced)
    r = course_only.handle_message(sid, "who won the football world cup?")
    assert not r.escalated and r.reply == course_only.settings.rag.offtopic_reply


def test_explicit_requests_are_honoured_not_explored(make_orch: MakeOrch) -> None:
    """With explore_on_requests off (the default), a learner who asks for a hint gets the
    proposer's choice, logged with propensity 1; other turns still explore."""
    orch = make_orch(with_mode("collect"))
    sid = orch.start_session("lrn_requests").session_id
    orch.handle_message(sid, "My goal is to finish 2 for loop exercises today")
    for text in ["Can I get a hint?", "Can you show me a similar example?", "Quiz me"] * 2:
        r = orch.handle_message(sid, text)
        assert r.propensity == 1.0, (text, r.action_id)


def test_open_mode_answers_any_question_and_labels_the_source(
    make_orch: MakeOrch, session_factory: sessionmaker[Session]
) -> None:
    """A course question answered from the notes cites them ("course"); a general question
    gets a general-knowledge answer ("general"); follow-ups see the earlier conversation."""
    from mentora.llm.backends.fake import FakeLLM
    from mentora.llm.types import LLMRequest

    seen: list[LLMRequest] = []

    def model(req: LLMRequest) -> str:
        seen.append(req)
        if "range" in req.messages[-1].content.split("<learner_message>")[-1]:
            return (
                "`range(5)` gives 0, 1, 2, 3 and 4: it starts at 0 and stops before 5 "
                "[syn101-week3-loops-p002]."
            )
        return "Paris is the capital of France."

    orch = make_orch(with_mode("deploy"), fake=FakeLLM(default=model))
    sid = orch.start_session("lrn_open").session_id
    orch.handle_message(sid, "My goal is to finish 2 for loop exercises today")
    course = orch.handle_message(sid, "Does range(5) include 5?")
    assert course.action_id == "WAIT" and course.answer_source == "course"
    assert course.passage_ids == ["syn101-week3-loops-p002"] and not course.escalated
    general = orch.handle_message(sid, "What is the capital of France?")
    assert general.answer_source == "general" and general.reply == "Paris is the capital of France."
    assert not general.passage_ids and not general.escalated
    last = seen[-1]
    assert last.prompt_id.startswith("tutor/answer")
    assert any("range" in m.content for m in last.messages[:-1])  # earlier turns as history
