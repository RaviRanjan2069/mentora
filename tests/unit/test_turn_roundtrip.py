"""M1 'done when': insert and read back a full turn's events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mentora.db import models as m
from mentora.logging_xapi.lrs_client import SqlLRSClient, StatementConflictError
from mentora.logging_xapi.statements import (
    ActionRef,
    FilterOutcome,
    TutorActionExtension,
    learner_message,
    quiz_answer,
    tutor_action,
)

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def test_full_turn_roundtrip(
    session_factory: sessionmaker[Session], seeded: dict[str, str]
) -> None:
    lid, sid = seeded["learner_id"], seeded["session_id"]
    lrs = SqlLRSClient(session_factory)

    hint = ActionRef(agent="ContentTutor", move="graded_hint", style="Socratic")
    ext = TutorActionExtension(
        policy_version="rule-v1",
        action=hint,
        propensity=0.62,
        filter_outcome=FilterOutcome(
            feasible_action_ids=[hint.id, "WAIT", "ESCALATE"],
            removed={"integrity": ["ContentTutor.worked_example.Socratic"]},
        ),
        retrieved_passage_ids=["syn-w2-p03", "syn-w2-p04"],
        prompt_version="content_tutor/graded_hint/v1",
        model="fake",
    )
    turn = [
        quiz_answer(
            lid, sid, 1, item_id=7, response="B", success=False, confidence=0.8, timestamp=T0
        ),
        learner_message(
            lid, sid, 1, "I don't get why B is wrong", timestamp=T0 + timedelta(seconds=5)
        ),
        tutor_action(
            lid,
            sid,
            1,
            ext,
            "What does the loop do on its last pass? [syn-w2-p03]",
            timestamp=T0 + timedelta(seconds=6),
        ),
    ]
    assert lrs.store_many(turn) == [st.id for st in turn]

    with session_factory.begin() as db:
        db.add(
            m.Transition(
                learner_id=lid,
                session_id=sid,
                t=1,
                state=[0.4, 0.1, 1.0, 0.0],
                action_id=hint.id,
                propensity=ext.propensity,
                policy_version="rule-v1",
            )
        )

    # Read back: full statements, in order, unchanged.
    back = lrs.query(session_id=sid)
    assert back == turn
    assert back[2].tutor_action == ext

    # Denormalised columns match the tutor extension.
    with session_factory() as db:
        row = db.get(m.Event, turn[2].id)
        assert row is not None
        assert (row.action_id, row.propensity, row.policy_version, row.escalated) == (
            hint.id,
            0.62,
            "rule-v1",
            False,
        )
        assert row.timestamp == T0 + timedelta(seconds=6)
        learner_rows = db.scalars(select(m.Event).where(m.Event.action_id.is_(None))).all()
        assert len(learner_rows) == 2
        tr = db.scalars(select(m.Transition)).one()
        assert tr.reward is None and tr.next_state is None  # filled at the next step

    assert [s.verb.display["en-US"] for s in lrs.query(learner_id=lid, verb="answered")] == [
        "answered"
    ]
    assert len(lrs.query(session_id=sid, since=T0 + timedelta(seconds=5))) == 2


def test_storing_same_statement_twice_is_idempotent(
    session_factory: sessionmaker[Session], seeded: dict[str, str]
) -> None:
    lrs = SqlLRSClient(session_factory)
    st = learner_message(seeded["learner_id"], seeded["session_id"], 1, "hi", timestamp=T0)
    lrs.store(st)
    lrs.store(st)
    assert len(lrs.query(session_id=seeded["session_id"])) == 1

    clash = learner_message(
        seeded["learner_id"], seeded["session_id"], 1, "other", timestamp=T0
    ).model_copy(update={"id": st.id})
    with pytest.raises(StatementConflictError):
        lrs.store(clash)


def test_db_rejects_out_of_range_propensity(
    session_factory: sessionmaker[Session], seeded: dict[str, str]
) -> None:
    with pytest.raises(IntegrityError), session_factory.begin() as db:
        db.add(
            m.Transition(
                learner_id=seeded["learner_id"],
                session_id=seeded["session_id"],
                t=1,
                state=[0.0],
                action_id="WAIT",
                propensity=0.0,
                policy_version="rule-v1",
            )
        )


def test_unknown_learner_cannot_log(session_factory: sessionmaker[Session]) -> None:
    with pytest.raises(IntegrityError):
        SqlLRSClient(session_factory).store(learner_message("lrn_ghost", None, 1, "hi"))  # type: ignore[arg-type]
