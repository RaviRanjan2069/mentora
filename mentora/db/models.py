"""Schema v1 (frozen). See docs/schema.md. Change only through a new Alembic migration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from mentora.db.base import Base
from mentora.db.types import Embedding, PortableJSON, UTCDateTime

# Must equal rag.embedding_dim in defaults.yaml (checked by tests/unit/test_settings.py).
EMBEDDING_DIM = 384


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


concept_prerequisites = Table(
    "concept_prerequisites",
    Base.metadata,
    Column("concept_id", ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True),
    Column("prerequisite_id", ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True),
    CheckConstraint("concept_id <> prerequisite_id", name="no_self_prereq"),
)

item_concepts = Table(
    "item_concepts",
    Base.metadata,
    Column("item_id", ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
    Column("concept_id", ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True),
)


class Learner(Base):
    __tablename__ = "learners"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # pseudonym, never raw LMS id
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    # Self-reported / derived group attributes, used only for the fairness check.
    gender: Mapped[str | None] = mapped_column(String(32))
    prior_achievement_tercile: Mapped[int | None] = mapped_column(Integer)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    lti_context_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class Concept(Base):
    __tablename__ = "concepts"
    __table_args__ = (UniqueConstraint("course_id", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    external_id: Mapped[str | None] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    item_type: Mapped[str] = mapped_column(String(32), default="mcq")
    answer_key: Mapped[str | None] = mapped_column(Text)
    graded: Mapped[bool] = mapped_column(Boolean, default=False)  # integrity rules apply if True


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (CheckConstraint("mode IN ('adaptive', 'static')", name="mode"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id", ondelete="CASCADE"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(16), default="adaptive")
    policy_version: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Event(Base):
    """One xAPI statement. ``statement`` is the source of truth; other columns are
    denormalised copies for querying."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_learner_ts", "learner_id", "timestamp"),
        Index("ix_events_session_ts", "session_id", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # xAPI statement id
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id", ondelete="CASCADE"))
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    turn: Mapped[int | None] = mapped_column(Integer)
    verb: Mapped[str] = mapped_column(String(255))
    object_id: Mapped[str] = mapped_column(String(512))
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime)
    stored_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    statement: Mapped[dict[str, Any]] = mapped_column(PortableJSON)
    # Tutor-action fields (NULL for learner/LMS events).
    policy_version: Mapped[str | None] = mapped_column(String(64))
    action_id: Mapped[str | None] = mapped_column(String(128))
    propensity: Mapped[float | None] = mapped_column(Float)
    escalated: Mapped[bool | None] = mapped_column(Boolean)


class Goal(Base):
    __tablename__ = "goals"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'attained', 'abandoned')", name="status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id", ondelete="CASCADE"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    concept_keys: Mapped[list[str]] = mapped_column(PortableJSON, default=list)
    smart_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    attained_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"))
    steps: Mapped[list[dict[str, Any]]] = mapped_column(PortableJSON, default=list)
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # rho_t in [0, 1]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)


class MemoryItem(Base):
    __tablename__ = "memory_items"
    __table_args__ = (
        Index("ix_memory_items_learner_status", "learner_id", "status"),
        CheckConstraint("scope IN ('learner', 'course')", name="scope"),
        CheckConstraint("status IN ('active', 'pending_review', 'pruned')", name="status"),
        CheckConstraint("scope = 'course' OR learner_id IS NOT NULL", name="learner_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(16))
    learner_id: Mapped[str | None] = mapped_column(ForeignKey("learners.id", ondelete="CASCADE"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Embedding(EMBEDDING_DIM))
    n_plus: Mapped[int] = mapped_column(Integer, default=0)
    n_minus: Mapped[int] = mapped_column(Integer, default=0)
    quality: Mapped[float] = mapped_column(Float, default=0.5)  # (n_plus+1)/(n_plus+n_minus+2)
    status: Mapped[str] = mapped_column(String(16), default="active")
    source_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Transition(Base):
    """(s, a, mu, r, s') for offline RL. reward/next_state are filled one step later."""

    __tablename__ = "transitions"
    __table_args__ = (
        UniqueConstraint("session_id", "t"),
        Index("ix_transitions_learner", "learner_id"),
        CheckConstraint("propensity > 0 AND propensity <= 1", name="propensity_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id", ondelete="CASCADE"))
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    t: Mapped[int] = mapped_column(Integer)
    state: Mapped[list[float]] = mapped_column(PortableJSON)  # numeric s_t only (rule 5)
    action_id: Mapped[str] = mapped_column(String(128))
    propensity: Mapped[float] = mapped_column(Float)
    reward: Mapped[float | None] = mapped_column(Float)
    next_state: Mapped[list[float] | None] = mapped_column(PortableJSON)
    policy_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate', 'approved', 'rejected', 'active', 'retired')", name="status"
        ),
    )

    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(32))  # rule | collect | tabular | cql_ensemble
    config: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="candidate")
    approved_by: Mapped[str | None] = mapped_column(String(255))
    reasons: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Escalation(Base):
    __tablename__ = "escalations"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'answered', 'closed')", name="status"),
        Index("ix_escalations_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id", ondelete="CASCADE"))
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"))
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"))
    # distress | grounding_failure | uncertainty | teacher_rule | other
    reason: Mapped[str] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")
    teacher_response: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class TeacherRule(Base):
    __tablename__ = "teacher_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    # Structured, never free text: e.g. {"forbid": {"agent": "PeerBroker"}, "when": {"week_lte": 1}}
    rule: Mapped[dict[str, Any]] = mapped_column(PortableJSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class CorpusPassage(Base):
    __tablename__ = "corpus_passages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # citable passage id
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Embedding(EMBEDDING_DIM))
    concept_keys: Mapped[list[str]] = mapped_column(PortableJSON, default=list)
    section: Mapped[str | None] = mapped_column(String(255))
    week: Mapped[int | None] = mapped_column(Integer)
    source_file: Mapped[str | None] = mapped_column(String(512))
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id", ondelete="CASCADE"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    consent_type: Mapped[str] = mapped_column(String(32))  # tutoring | research_logging
    granted: Mapped[bool] = mapped_column(Boolean)
    form_version: Mapped[str] = mapped_column(String(32))
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
