"""The MongoDB unit of work keeps the guarantees the code relied on from SQL."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from mentora.db import DESC, IntegrityError, StoreFactory, connect
from mentora.db import models as m
from mentora.db.client import drop_mock

URL = "mongomock://test_store"


@pytest.fixture
def factory() -> Iterator[StoreFactory]:
    drop_mock(URL)
    yield connect(URL)
    drop_mock(URL)


def _course_learner_session(factory: StoreFactory) -> tuple[int, str, str]:
    with factory.begin() as db:
        course = m.Course(code="C1", title="Course")
        learner = m.Learner(id="lrn_a")
        db.add_all([course, learner])
        db.flush()
        sess = m.Session(learner_id=learner.id, course_id=course.id)
        db.add(sess)
        db.flush()
        return course.id, learner.id, sess.id


def test_counter_ids_and_identity_map(factory: StoreFactory) -> None:
    with factory.begin() as db:
        a, b = m.Course(code="A", title="a"), m.Course(code="B", title="b")
        db.add_all([a, b])
        db.flush()
        assert (a.id, b.id) == (1, 2)
        assert db.get(m.Course, 1) is a
        assert db.find_one(m.Course, {"code": "A"}) is a
        assert db.find_one(m.Course, {"id": 2}) is b  # "id" means _id in filters


def test_load_mutate_commit_is_saved(factory: StoreFactory) -> None:
    _, _, sid = _course_learner_session(factory)
    with factory() as db:
        sess = db.get(m.Session, sid)
        assert sess is not None
        sess.ended_at = datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)
        db.commit()
    with factory() as db:
        got = db.get(m.Session, sid)
        assert got is not None and got.ended_at == datetime(2026, 1, 1, 12, 0, 0, 123000, tzinfo=UTC)


def test_leaving_without_commit_or_with_error_undoes_writes(factory: StoreFactory) -> None:
    with factory() as db:
        db.add(m.Course(code="X", title="x"))
        db.flush()
    with pytest.raises(RuntimeError), factory.begin() as db:
        db.add(m.Course(code="Y", title="y"))
        db.flush()
        raise RuntimeError
    with factory() as db:
        assert db.count(m.Course) == 0


def test_constraints_references_and_unique(factory: StoreFactory) -> None:
    cid, lid, sid = _course_learner_session(factory)
    with pytest.raises(IntegrityError), factory.begin() as db:
        db.add(m.Session(learner_id="lrn_ghost", course_id=cid))
    with pytest.raises(IntegrityError), factory.begin() as db:
        db.add(m.Course(code="C1", title="duplicate code"))
    with pytest.raises(IntegrityError), factory.begin() as db:
        db.add(m.Goal(learner_id=lid, course_id=cid, text="g", status="maybe"))
    with factory.begin() as db:
        db.add(
            m.Transition(
                learner_id=lid, session_id=sid, t=1, state=[0.0], action_id="WAIT",
                propensity=1.0, policy_version="rule-v1",
            )
        )
    with pytest.raises(IntegrityError), factory.begin() as db:
        db.add(
            m.Transition(
                learner_id=lid, session_id=sid, t=1, state=[0.0], action_id="WAIT",
                propensity=1.0, policy_version="rule-v1",
            )
        )


def test_deleting_a_learner_cascades_and_sets_null(factory: StoreFactory) -> None:
    cid, lid, sid = _course_learner_session(factory)
    with factory.begin() as db:
        goal = m.Goal(learner_id=lid, course_id=cid, session_id=sid, text="g")
        db.add(goal)
        db.flush()
        db.add(m.Plan(goal_id=goal.id))
        db.add(m.MemoryItem(scope="course", course_id=cid, text="t", source_session_id=sid))
        db.add(
            m.Event(
                id="ev1", learner_id=lid, session_id=sid, verb="v", object_id="o",
                timestamp=datetime.now(UTC), statement={},
            )
        )
    with factory.begin() as db:
        assert db.delete_many(m.Learner, {"id": lid}) == 1
    with factory() as db:
        for model in (m.Session, m.Goal, m.Plan, m.Event):
            assert db.count(model) == 0, model
        course_memory = db.find_one(m.MemoryItem, {"scope": "course"})
        assert course_memory is not None and course_memory.source_session_id is None


def test_savepoint_undoes_only_its_block(factory: StoreFactory) -> None:
    with factory.begin() as db:
        db.add(m.Course(code="keep", title="k"))
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(m.Course(code="keep", title="duplicate"))
        db.add(m.Course(code="also", title="a"))
    with factory() as db:
        assert sorted(c.code for c in db.find(m.Course)) == ["also", "keep"]


def test_find_sort_limit_values_distinct(factory: StoreFactory) -> None:
    with factory.begin() as db:
        db.add_all([m.Course(code=c, title=c.upper()) for c in "bac"])
    with factory() as db:
        assert [c.code for c in db.find(m.Course, sort=[("code", DESC)], limit=2)] == ["c", "b"]
        assert db.values(m.Course, ["code", "title"], {"code": "a"}) == [("a", "A")]
        assert sorted(db.distinct(m.Course, "code")) == ["a", "b", "c"]
        assert db.update_many(m.Course, {"code": {"$in": ["a", "b"]}}, {"title": "z"}) == 2
        assert db.count(m.Course, {"title": "z"}) == 2
