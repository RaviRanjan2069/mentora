"""MongoDB connections and the schema (indexes and unique constraints).

URLs: ``mongodb://host:27017/mentora`` or ``mongodb+srv://user:pw@cluster/mentora``
(database name from the path, default ``mentora``), or ``mongomock://<name>`` for an
in-memory database (tests). ``ensure_schema`` replaces SQL migrations: it is idempotent
and runs on API start and in ``scripts/init_db.py``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from pymongo import ASCENDING, IndexModel, MongoClient
from pymongo.database import Database

from mentora.db.store import StoreFactory

SCHEMA_VERSION = "v1-mongo"

# collection -> indexes; unique ones replace SQL UNIQUE constraints.
INDEXES: dict[str, list[IndexModel]] = {
    "courses": [IndexModel([("code", ASCENDING)], unique=True, name="uq_courses_code")],
    "concepts": [
        IndexModel(
            [("course_id", ASCENDING), ("key", ASCENDING)], unique=True, name="uq_concepts_key"
        )
    ],
    "items": [IndexModel([("course_id", ASCENDING)], name="ix_items_course")],
    "sessions": [
        IndexModel([("learner_id", ASCENDING)], name="ix_sessions_learner"),
        IndexModel([("course_id", ASCENDING)], name="ix_sessions_course"),
    ],
    "events": [
        IndexModel([("learner_id", ASCENDING), ("timestamp", ASCENDING)], name="ix_events_learner_ts"),
        IndexModel([("session_id", ASCENDING), ("timestamp", ASCENDING)], name="ix_events_session_ts"),
    ],
    "goals": [IndexModel([("learner_id", ASCENDING)], name="ix_goals_learner")],
    "plans": [IndexModel([("goal_id", ASCENDING)], name="ix_plans_goal")],
    "memory_items": [
        IndexModel([("learner_id", ASCENDING), ("status", ASCENDING)], name="ix_memory_learner_status"),
        IndexModel([("course_id", ASCENDING), ("scope", ASCENDING)], name="ix_memory_course_scope"),
    ],
    "transitions": [
        IndexModel(
            [("session_id", ASCENDING), ("t", ASCENDING)], unique=True, name="uq_transitions_step"
        ),
        IndexModel([("learner_id", ASCENDING)], name="ix_transitions_learner"),
    ],
    "policies": [IndexModel([("status", ASCENDING)], name="ix_policies_status")],
    "escalations": [
        IndexModel([("status", ASCENDING)], name="ix_escalations_status"),
        IndexModel([("learner_id", ASCENDING)], name="ix_escalations_learner"),
    ],
    "teacher_rules": [IndexModel([("course_id", ASCENDING)], name="ix_teacher_rules_course")],
    "corpus_passages": [IndexModel([("course_id", ASCENDING)], name="ix_passages_course")],
    "consents": [IndexModel([("learner_id", ASCENDING)], name="ix_consents_learner")],
}

_MOCK_CLIENTS: dict[str, Any] = {}


def make_database(url: str) -> Database[dict[str, Any]]:
    parts = urlsplit(url)
    name = parts.path.strip("/") or "mentora"
    if parts.scheme == "mongomock":
        import mongomock

        name = parts.netloc or name
        client = _MOCK_CLIENTS.setdefault(name, mongomock.MongoClient(tz_aware=True))
        return client[name]  # type: ignore[no-any-return]
    if parts.scheme not in ("mongodb", "mongodb+srv"):
        raise ValueError(f"MENTORA_DATABASE_URL must be a mongodb:// URL, not {parts.scheme}://")
    client: MongoClient[dict[str, Any]] = MongoClient(
        url, tz_aware=True, serverSelectionTimeoutMS=10_000, appname="mentora"
    )
    return client[name]


def ensure_schema(database: Database[dict[str, Any]]) -> None:
    for name, indexes in INDEXES.items():
        database[name].create_indexes(indexes)
    database["meta"].update_one(
        {"_id": "schema"}, {"$set": {"version": SCHEMA_VERSION}}, upsert=True
    )


def connect(url: str, *, create_schema: bool = True) -> StoreFactory:
    """A StoreFactory for ``url``; creates indexes unless told not to."""
    database = make_database(url)
    if create_schema:
        ensure_schema(database)
    return StoreFactory(database)


def drop_mock(url: str) -> None:
    """Forget an in-memory database (tests)."""
    parts = urlsplit(url)
    _MOCK_CLIENTS.pop(parts.netloc or parts.path.strip("/") or "mentora", None)
