"""Runs only against a live MongoDB (CI service container, docker compose or a local
server). Uses a throwaway database that is dropped afterwards:

MENTORA_TEST_MONGODB_URL=mongodb://localhost:27017 pytest -m mongo
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from pymongo import MongoClient

from mentora.db import IntegrityError, StoreFactory, connect
from mentora.db import models as m
from mentora.db.client import INDEXES, SCHEMA_VERSION
from mentora.logging_xapi.lrs_client import SqlLRSClient
from mentora.logging_xapi.statements import (
    ActionRef,
    FilterOutcome,
    TutorActionExtension,
    learner_message,
    tutor_action,
)

pytestmark = pytest.mark.mongo


@pytest.fixture(scope="module")
def factory() -> Iterator[StoreFactory]:
    base = os.environ.get("MENTORA_TEST_MONGODB_URL", "mongodb://localhost:27017").rstrip("/")
    name = f"mentora_test_{uuid.uuid4().hex[:10]}"
    client: MongoClient[dict[str, object]] = MongoClient(base, serverSelectionTimeoutMS=3000)
    try:
        client.admin.command("ping")
    except Exception:
        pytest.skip(f"no MongoDB at {base}")
    try:
        yield connect(f"{base}/{name}")
    finally:
        client.drop_database(name)


def test_schema_indexes_exist(factory: StoreFactory) -> None:
    db = factory.database
    assert db["meta"].find_one({"_id": "schema"})["version"] == SCHEMA_VERSION  # type: ignore[index]
    for name, indexes in INDEXES.items():
        have = set(db[name].index_information())
        assert {i.document["name"] for i in indexes} <= have, name


def test_roundtrip_turn_vectors_and_constraints(factory: StoreFactory) -> None:
    with factory.begin() as db:
        course = m.Course(code="MG101", title="Mongo course")
        learner = m.Learner(id="lrn_mg")
        db.add_all([course, learner])
        db.flush()
        sess = m.Session(learner_id=learner.id, course_id=course.id)
        db.add(sess)
        db.add(m.CorpusPassage(id="mg-p1", course_id=course.id, text="x", embedding=[0.1] * 384))
        db.flush()
        sid = sess.id

    ext = TutorActionExtension(
        policy_version="rule-v1",
        action=ActionRef(move="WAIT"),
        propensity=1.0,
        filter_outcome=FilterOutcome(feasible_action_ids=["WAIT"]),
    )
    turn = [learner_message("lrn_mg", sid, 1, "ok"), tutor_action("lrn_mg", sid, 1, ext, None)]
    lrs = SqlLRSClient(factory)
    lrs.store_many(turn)
    assert lrs.query(session_id=sid) == turn

    with factory() as db:
        p = db.get(m.CorpusPassage, "mg-p1")
        assert p is not None and p.embedding is not None and len(p.embedding) == 384
        got = db.get(m.Session, sid)
        assert got is not None and got.started_at.tzinfo is not None
        assert got.started_at <= datetime.now(UTC)

    with pytest.raises(IntegrityError), factory.begin() as db:
        db.add(m.Course(code="MG101", title="duplicate"))  # unique index on a real server

    with factory.begin() as db:
        assert db.delete_many(m.Learner, {"id": "lrn_mg"}) == 1
    with factory() as db:
        assert db.count(m.Session, {"learner_id": "lrn_mg"}) == 0
        assert db.count(m.Event, {"learner_id": "lrn_mg"}) == 0
