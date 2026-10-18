"""Schema v1 (frozen). Written out in full so later model edits cannot silently change it.

Revision ID: 0001
Revises:
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIM = 384
TS = sa.DateTime(timezone=True)


def _fk(col: str, table: str, ref: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [col], [f"{ref}.id"], name=f"fk_{table}_{col}_{ref}", ondelete=ondelete
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("lti_context_id", sa.String(255)),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_courses"),
        sa.UniqueConstraint("code", name="uq_courses_code"),
    )
    op.create_table(
        "learners",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("gender", sa.String(32)),
        sa.Column("prior_achievement_tercile", sa.Integer()),
        sa.PrimaryKeyConstraint("id", name="pk_learners"),
    )
    op.create_table(
        "policies",
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("metrics", JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("approved_by", sa.String(255)),
        sa.Column("reasons", sa.Text()),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("decided_at", TS),
        sa.PrimaryKeyConstraint("version", name="pk_policies"),
        sa.CheckConstraint(
            "status IN ('candidate', 'approved', 'rejected', 'active', 'retired')",
            name=op.f("ck_policies_status"),
        ),
    )
    op.create_table(
        "concepts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.PrimaryKeyConstraint("id", name="pk_concepts"),
        sa.UniqueConstraint("course_id", "key", name="uq_concepts_course_id"),
        _fk("course_id", "concepts", "courses", "CASCADE"),
    )
    op.create_table(
        "consents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("learner_id", sa.String(64), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("consent_type", sa.String(32), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("form_version", sa.String(32), nullable=False),
        sa.Column("recorded_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_consents"),
        _fk("learner_id", "consents", "learners", "CASCADE"),
        _fk("course_id", "consents", "courses", "CASCADE"),
    )
    op.create_table(
        "corpus_passages",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(DIM)),
        sa.Column("concept_keys", JSONB(), nullable=False),
        sa.Column("section", sa.String(255)),
        sa.Column("week", sa.Integer()),
        sa.Column("source_file", sa.String(512)),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_corpus_passages"),
        _fk("course_id", "corpus_passages", "courses", "CASCADE"),
    )
    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(255)),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("item_type", sa.String(32), nullable=False),
        sa.Column("answer_key", sa.Text()),
        sa.Column("graded", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_items"),
        _fk("course_id", "items", "courses", "CASCADE"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("learner_id", sa.String(64), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("policy_version", sa.String(64)),
        sa.Column("started_at", TS, nullable=False),
        sa.Column("ended_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.CheckConstraint("mode IN ('adaptive', 'static')", name=op.f("ck_sessions_mode")),
        _fk("learner_id", "sessions", "learners", "CASCADE"),
        _fk("course_id", "sessions", "courses", "CASCADE"),
    )
    op.create_table(
        "teacher_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("rule", JSONB(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(255)),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_teacher_rules"),
        _fk("course_id", "teacher_rules", "courses", "CASCADE"),
    )
    op.create_table(
        "concept_prerequisites",
        sa.Column("concept_id", sa.Integer(), nullable=False),
        sa.Column("prerequisite_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("concept_id", "prerequisite_id", name="pk_concept_prerequisites"),
        sa.CheckConstraint(
            "concept_id <> prerequisite_id", name=op.f("ck_concept_prerequisites_no_self_prereq")
        ),
        _fk("concept_id", "concept_prerequisites", "concepts", "CASCADE"),
        _fk("prerequisite_id", "concept_prerequisites", "concepts", "CASCADE"),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("learner_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(36)),
        sa.Column("turn", sa.Integer()),
        sa.Column("verb", sa.String(255), nullable=False),
        sa.Column("object_id", sa.String(512), nullable=False),
        sa.Column("timestamp", TS, nullable=False),
        sa.Column("stored_at", TS, nullable=False),
        sa.Column("statement", JSONB(), nullable=False),
        sa.Column("policy_version", sa.String(64)),
        sa.Column("action_id", sa.String(128)),
        sa.Column("propensity", sa.Float()),
        sa.Column("escalated", sa.Boolean()),
        sa.PrimaryKeyConstraint("id", name="pk_events"),
        _fk("learner_id", "events", "learners", "CASCADE"),
        _fk("session_id", "events", "sessions", "CASCADE"),
    )
    op.create_index("ix_events_session_ts", "events", ["session_id", "timestamp"])
    op.create_index("ix_events_learner_ts", "events", ["learner_id", "timestamp"])
    op.create_table(
        "goals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("learner_id", sa.String(64), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(36)),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("concept_keys", JSONB(), nullable=False),
        sa.Column("smart_score", sa.Float()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("attained_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_goals"),
        sa.CheckConstraint(
            "status IN ('active', 'attained', 'abandoned')", name=op.f("ck_goals_status")
        ),
        _fk("learner_id", "goals", "learners", "CASCADE"),
        _fk("course_id", "goals", "courses", "CASCADE"),
        _fk("session_id", "goals", "sessions", "SET NULL"),
    )
    op.create_table(
        "item_concepts",
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("concept_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("item_id", "concept_id", name="pk_item_concepts"),
        _fk("item_id", "item_concepts", "items", "CASCADE"),
        _fk("concept_id", "item_concepts", "concepts", "CASCADE"),
    )
    op.create_table(
        "memory_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("learner_id", sa.String(64)),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(DIM)),
        sa.Column("n_plus", sa.Integer(), nullable=False),
        sa.Column("n_minus", sa.Integer(), nullable=False),
        sa.Column("quality", sa.Float(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_session_id", sa.String(36)),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_used_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_memory_items"),
        sa.CheckConstraint("scope IN ('learner', 'course')", name=op.f("ck_memory_items_scope")),
        sa.CheckConstraint(
            "status IN ('active', 'pending_review', 'pruned')", name=op.f("ck_memory_items_status")
        ),
        sa.CheckConstraint(
            "scope = 'course' OR learner_id IS NOT NULL", name=op.f("ck_memory_items_learner_scope")
        ),
        _fk("learner_id", "memory_items", "learners", "CASCADE"),
        _fk("course_id", "memory_items", "courses", "CASCADE"),
        _fk("source_session_id", "memory_items", "sessions", "SET NULL"),
    )
    op.create_index("ix_memory_items_learner_status", "memory_items", ["learner_id", "status"])
    op.create_table(
        "transitions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("learner_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("t", sa.Integer(), nullable=False),
        sa.Column("state", JSONB(), nullable=False),
        sa.Column("action_id", sa.String(128), nullable=False),
        sa.Column("propensity", sa.Float(), nullable=False),
        sa.Column("reward", sa.Float()),
        sa.Column("next_state", JSONB()),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_transitions"),
        sa.UniqueConstraint("session_id", "t", name="uq_transitions_session_id"),
        sa.CheckConstraint(
            "propensity > 0 AND propensity <= 1", name=op.f("ck_transitions_propensity_range")
        ),
        _fk("learner_id", "transitions", "learners", "CASCADE"),
        _fk("session_id", "transitions", "sessions", "CASCADE"),
    )
    op.create_index("ix_transitions_learner", "transitions", ["learner_id"])
    op.create_table(
        "escalations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("learner_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(36)),
        sa.Column("event_id", sa.String(36)),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("teacher_response", sa.Text()),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("resolved_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_escalations"),
        sa.CheckConstraint(
            "status IN ('open', 'answered', 'closed')", name=op.f("ck_escalations_status")
        ),
        _fk("learner_id", "escalations", "learners", "CASCADE"),
        _fk("session_id", "escalations", "sessions", "SET NULL"),
        _fk("event_id", "escalations", "events", "SET NULL"),
    )
    op.create_index("ix_escalations_status", "escalations", ["status"])
    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("goal_id", sa.Integer(), nullable=False),
        sa.Column("steps", JSONB(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_plans"),
        _fk("goal_id", "plans", "goals", "CASCADE"),
    )


def downgrade() -> None:
    for table in [
        "plans",
        "escalations",
        "transitions",
        "memory_items",
        "item_concepts",
        "goals",
        "events",
        "concept_prerequisites",
        "teacher_rules",
        "sessions",
        "items",
        "corpus_passages",
        "consents",
        "concepts",
        "policies",
        "learners",
        "courses",
    ]:
        op.drop_table(table)
