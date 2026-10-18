"""Runs only against a live PostgreSQL + pgvector (CI service container or docker compose):

MENTORA_DATABASE_URL=postgresql+psycopg://mentora:mentora@localhost:5432/mentora pytest -m postgres
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from mentora.db import make_engine, make_session_factory
from mentora.db import models as m
from mentora.logging_xapi.lrs_client import SqlLRSClient
from mentora.logging_xapi.statements import (
    ActionRef,
    FilterOutcome,
    TutorActionExtension,
    learner_message,
    tutor_action,
)

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def pg_url() -> str:
    url = os.environ.get("MENTORA_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("MENTORA_DATABASE_URL does not point at PostgreSQL")
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return url


def test_migrated_db_roundtrips_turn_and_vectors(pg_url: str) -> None:
    engine = make_engine(pg_url)
    factory = make_session_factory(engine)
    with factory.begin() as db:
        course = m.Course(code="PG101", title="PG course")
        learner = m.Learner(id="lrn_pg")
        db.add_all([course, learner])
        db.flush()
        sess = m.Session(learner_id=learner.id, course_id=course.id)
        db.add(sess)
        db.flush()
        db.add(m.CorpusPassage(id="pg-p1", course_id=course.id, text="x", embedding=[0.1] * 384))
        sid = sess.id

    wait = ActionRef(move="WAIT")
    ext = TutorActionExtension(
        policy_version="rule-v1",
        action=wait,
        propensity=1.0,
        filter_outcome=FilterOutcome(feasible_action_ids=["WAIT"]),
    )
    turn = [learner_message("lrn_pg", sid, 1, "ok"), tutor_action("lrn_pg", sid, 1, ext, None)]
    lrs = SqlLRSClient(factory)
    lrs.store_many(turn)
    assert lrs.query(session_id=sid) == turn

    with factory() as db:
        assert db.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'")).scalar()
        p = db.scalars(select(m.CorpusPassage)).one()
        assert p.embedding is not None and len(p.embedding) == 384
