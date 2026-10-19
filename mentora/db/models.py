"""Collections (schema "v1-mongo"). See docs/schema.md.

Same entities and field names as SQL schema v1. Many-to-many link tables are embedded
lists: ``Concept.prerequisite_ids`` and ``Item.concept_ids``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from mentora.db.documents import Document, IdKind, Ref, check, embedding_ok, now, one_of

# Must equal rag.embedding_dim in defaults.yaml (checked by tests/unit/test_settings.py).
EMBEDDING_DIM = 384


def _uuid() -> str:
    return str(uuid.uuid4())


LEARNER = Ref("learners", "cascade")
COURSE = Ref("courses", "cascade")
SESSION = Ref("sessions", "cascade")
SESSION_OR_NULL = Ref("sessions", "set_null")


@dataclass(kw_only=True)
class Learner(Document):
    __collection__ = "learners"
    __id_kind__: ClassVar[IdKind] = "given"

    id: str  # pseudonym, never raw LMS id
    created_at: datetime = field(default_factory=now)
    # Self-reported / derived group attributes, used only for the fairness check.
    gender: str | None = None
    prior_achievement_tercile: int | None = None


@dataclass(kw_only=True)
class Course(Document):
    __collection__ = "courses"

    id: int = 0
    code: str  # unique
    title: str
    lti_context_id: str | None = None
    created_at: datetime = field(default_factory=now)


@dataclass(kw_only=True)
class Concept(Document):
    __collection__ = "concepts"  # unique (course_id, key)
    __refs__: ClassVar[Mapping[str, Ref]] = {"course_id": COURSE}

    id: int = 0
    course_id: int
    key: str
    name: str
    description: str | None = None
    prerequisite_ids: list[int] = field(default_factory=list)

    def validate(self) -> None:
        check(self.id not in self.prerequisite_ids, "a concept cannot be its own prerequisite")


@dataclass(kw_only=True)
class Item(Document):
    __collection__ = "items"
    __refs__: ClassVar[Mapping[str, Ref]] = {"course_id": COURSE}

    id: int = 0
    course_id: int
    external_id: str | None = None
    text: str
    item_type: str = "mcq"
    answer_key: str | None = None
    graded: bool = False  # integrity rules apply if True
    concept_ids: list[int] = field(default_factory=list)


@dataclass(kw_only=True)
class Session(Document):
    __collection__ = "sessions"
    __id_kind__: ClassVar[IdKind] = "uuid"
    __refs__: ClassVar[Mapping[str, Ref]] = {"learner_id": LEARNER, "course_id": COURSE}

    id: str = field(default_factory=_uuid)
    learner_id: str
    course_id: int
    mode: str = "adaptive"
    policy_version: str | None = None
    started_at: datetime = field(default_factory=now)
    ended_at: datetime | None = None

    def validate(self) -> None:
        one_of(self.mode, ("adaptive", "static"), "mode")


@dataclass(kw_only=True)
class Event(Document):
    """One xAPI statement. ``statement`` is the source of truth; other fields are
    denormalised copies for querying."""

    __collection__ = "events"
    __id_kind__: ClassVar[IdKind] = "given"
    __refs__: ClassVar[Mapping[str, Ref]] = {"learner_id": LEARNER, "session_id": SESSION}
    __sequence__ = "seq"

    id: str  # xAPI statement id
    seq: int = 0  # insertion order (tie-break when sorting by timestamp)
    learner_id: str
    session_id: str | None = None
    turn: int | None = None
    verb: str
    object_id: str
    timestamp: datetime
    stored_at: datetime = field(default_factory=now)
    statement: dict[str, Any]
    # Tutor-action fields (None for learner/LMS events).
    policy_version: str | None = None
    action_id: str | None = None
    propensity: float | None = None
    escalated: bool | None = None


@dataclass(kw_only=True)
class Goal(Document):
    __collection__ = "goals"
    __refs__: ClassVar[Mapping[str, Ref]] = {
        "learner_id": LEARNER,
        "course_id": COURSE,
        "session_id": SESSION_OR_NULL,
    }

    id: int = 0
    learner_id: str
    course_id: int
    session_id: str | None = None
    text: str
    concept_keys: list[str] = field(default_factory=list)
    smart_score: float | None = None
    status: str = "active"
    created_at: datetime = field(default_factory=now)
    attained_at: datetime | None = None

    def validate(self) -> None:
        one_of(self.status, ("active", "attained", "abandoned"), "status")


@dataclass(kw_only=True)
class Plan(Document):
    __collection__ = "plans"
    __refs__: ClassVar[Mapping[str, Ref]] = {"goal_id": Ref("goals", "cascade")}
    __onupdate__: ClassVar[Mapping[str, Callable[[], Any]]] = {"updated_at": now}

    id: int = 0
    goal_id: int
    steps: list[dict[str, Any]] = field(default_factory=list)
    progress: float = 0.0  # rho_t in [0, 1]
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)


@dataclass(kw_only=True)
class MemoryItem(Document):
    __collection__ = "memory_items"
    __refs__: ClassVar[Mapping[str, Ref]] = {
        "learner_id": LEARNER,
        "course_id": COURSE,
        "source_session_id": SESSION_OR_NULL,
    }

    id: int = 0
    scope: str
    learner_id: str | None = None
    course_id: int
    text: str
    embedding: list[float] | None = None
    n_plus: int = 0
    n_minus: int = 0
    quality: float = 0.5  # (n_plus+1)/(n_plus+n_minus+2)
    status: str = "active"
    source_session_id: str | None = None
    created_at: datetime = field(default_factory=now)
    last_used_at: datetime | None = None

    def validate(self) -> None:
        one_of(self.scope, ("learner", "course"), "scope")
        one_of(self.status, ("active", "pending_review", "pruned"), "status")
        check(
            self.scope == "course" or self.learner_id is not None, "learner memory needs a learner"
        )
        self.embedding = embedding_ok(self.embedding, EMBEDDING_DIM, "embedding")


@dataclass(kw_only=True)
class Transition(Document):
    """(s, a, mu, r, s') for offline RL. reward/next_state are filled one step later."""

    __collection__ = "transitions"  # unique (session_id, t)
    __refs__: ClassVar[Mapping[str, Ref]] = {"learner_id": LEARNER, "session_id": SESSION}

    id: int = 0
    learner_id: str
    session_id: str
    t: int
    state: list[float]  # numeric s_t only (rule 5)
    action_id: str
    propensity: float
    reward: float | None = None
    next_state: list[float] | None = None
    policy_version: str
    created_at: datetime = field(default_factory=now)

    def validate(self) -> None:
        check(0 < self.propensity <= 1, f"propensity {self.propensity} not in (0, 1]")


@dataclass(kw_only=True)
class Policy(Document):
    __collection__ = "policies"
    __pk__ = "version"
    __id_kind__: ClassVar[IdKind] = "given"

    version: str
    type: str  # rule | collect | tabular | cql_ensemble
    config: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    status: str = "candidate"
    approved_by: str | None = None
    reasons: str | None = None
    created_at: datetime = field(default_factory=now)
    decided_at: datetime | None = None

    def validate(self) -> None:
        one_of(self.status, ("candidate", "approved", "rejected", "active", "retired"), "status")


@dataclass(kw_only=True)
class Escalation(Document):
    __collection__ = "escalations"
    __refs__: ClassVar[Mapping[str, Ref]] = {
        "learner_id": LEARNER,
        "session_id": SESSION_OR_NULL,
        "event_id": Ref("events", "set_null"),
    }

    id: int = 0
    learner_id: str
    session_id: str | None = None
    event_id: str | None = None
    # distress | grounding_failure | uncertainty | teacher_rule | other
    reason: str
    message: str | None = None
    status: str = "open"
    teacher_response: str | None = None
    created_at: datetime = field(default_factory=now)
    resolved_at: datetime | None = None

    def validate(self) -> None:
        one_of(self.status, ("open", "answered", "closed"), "status")


@dataclass(kw_only=True)
class TeacherRule(Document):
    __collection__ = "teacher_rules"
    __refs__: ClassVar[Mapping[str, Ref]] = {"course_id": COURSE}

    id: int = 0
    course_id: int
    name: str
    # Structured, never free text: e.g. {"forbid": {"agent": "PeerBroker"}, "when": {"week_lte": 1}}
    rule: dict[str, Any]
    active: bool = True
    created_by: str | None = None
    created_at: datetime = field(default_factory=now)


@dataclass(kw_only=True)
class CorpusPassage(Document):
    __collection__ = "corpus_passages"
    __id_kind__: ClassVar[IdKind] = "given"
    __refs__: ClassVar[Mapping[str, Ref]] = {"course_id": COURSE}

    id: str  # citable passage id
    course_id: int
    text: str
    embedding: list[float] | None = None
    concept_keys: list[str] = field(default_factory=list)
    section: str | None = None
    week: int | None = None
    source_file: str | None = None
    token_count: int = 0
    created_at: datetime = field(default_factory=now)

    def validate(self) -> None:
        self.embedding = embedding_ok(self.embedding, EMBEDDING_DIM, "embedding")


@dataclass(kw_only=True)
class Consent(Document):
    __collection__ = "consents"
    __refs__: ClassVar[Mapping[str, Ref]] = {"learner_id": LEARNER, "course_id": COURSE}

    id: int = 0
    learner_id: str
    course_id: int
    consent_type: str  # tutoring | research_logging
    granted: bool
    form_version: str
    recorded_at: datetime = field(default_factory=now)


# --- accounts (sign-up with a permanent user id; docs/decisions.md D41) -------------------------

ROLES = ("learner", "teacher")
GENDERS = ("female", "male", "non_binary", "prefer_not_to_say")
ACCOUNT = Ref("accounts", "cascade")


@dataclass(kw_only=True)
class Account(Document):
    """A person's sign-in identity. Learning data stays keyed by the pseudonym ``learner_id``."""

    __collection__ = "accounts"  # unique username, unique email
    __id_kind__: ClassVar[IdKind] = "uuid"
    # Deleting learning data never deletes the person's account (the reverse is done explicitly).
    __refs__: ClassVar[Mapping[str, Ref]] = {"learner_id": Ref("learners", "set_null")}

    id: str = field(default_factory=_uuid)
    username: str  # the permanent user id, lower case
    email: str  # lower case
    email_verified: bool = False
    role: str
    name: str
    gender: str = "prefer_not_to_say"
    password_hash: str
    session_version: int = 1
    failed_logins: int = 0
    locked_until: datetime | None = None
    learner_id: str | None = None  # learners only
    created_at: datetime = field(default_factory=now)
    last_login_at: datetime | None = None

    def validate(self) -> None:
        one_of(self.role, ROLES, "role")
        one_of(self.gender, GENDERS, "gender")
        check(self.username == self.username.lower(), "username must be lower case")
        check(self.email == self.email.lower(), "email must be lower case")


@dataclass(kw_only=True)
class AccountPhoto(Document):
    __collection__ = "account_photos"
    __id_kind__: ClassVar[IdKind] = "given"
    __refs__: ClassVar[Mapping[str, Ref]] = {"id": ACCOUNT}

    id: str  # the account id
    content_type: str
    data: bytes
    updated_at: datetime = field(default_factory=now)


@dataclass(kw_only=True)
class TeacherLink(Document):
    """A student's request to join a teacher, and the teacher's answer."""

    __collection__ = "teacher_links"  # unique (student_id, teacher_id)
    __refs__: ClassVar[Mapping[str, Ref]] = {"student_id": ACCOUNT, "teacher_id": ACCOUNT}

    id: int = 0
    student_id: str
    teacher_id: str
    status: str = "pending"
    created_at: datetime = field(default_factory=now)
    decided_at: datetime | None = None

    def validate(self) -> None:
        one_of(self.status, ("pending", "accepted", "declined"), "status")


@dataclass(kw_only=True)
class ClassCode(Document):
    """A teacher's permanent class code; students enter it to ask to join (one per teacher)."""

    __collection__ = "class_codes"  # unique teacher_id
    __id_kind__: ClassVar[IdKind] = "given"
    __refs__: ClassVar[Mapping[str, Ref]] = {"teacher_id": ACCOUNT}

    id: str  # the code, upper case
    teacher_id: str
    created_at: datetime = field(default_factory=now)

    def validate(self) -> None:
        check(self.id == self.id.upper(), "class codes are stored in upper case")


@dataclass(kw_only=True)
class EmailToken(Document):
    """A one-time link sent by email. Only the token's hash is stored."""

    __collection__ = "email_tokens"
    __id_kind__: ClassVar[IdKind] = "given"
    __refs__: ClassVar[Mapping[str, Ref]] = {"account_id": ACCOUNT}

    id: str  # sha256 of the token
    purpose: str
    account_id: str
    expires_at: datetime
    used: bool = False
    created_at: datetime = field(default_factory=now)

    def validate(self) -> None:
        one_of(self.purpose, ("verify", "reset"), "purpose")


MODELS: tuple[type[Document], ...] = (
    Learner,
    Course,
    Concept,
    Item,
    Session,
    Event,
    Goal,
    Plan,
    MemoryItem,
    Transition,
    Policy,
    Escalation,
    TeacherRule,
    CorpusPassage,
    Consent,
    Account,
    AccountPhoto,
    TeacherLink,
    EmailToken,
    ClassCode,
)
BY_COLLECTION: dict[str, type[Document]] = {model.__collection__: model for model in MODELS}
