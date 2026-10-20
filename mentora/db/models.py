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


# --- accounts (sign-up with a permanent user id; docs/decisions.md D41) --------------------------

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
    """A teacher's permanent class code, given at sign-up (10 random digits; older codes may
    be words); students enter it to ask to join. One per teacher, never changed."""

    __collection__ = "class_codes"  # unique teacher_id
    __id_kind__: ClassVar[IdKind] = "given"
    __refs__: ClassVar[Mapping[str, Ref]] = {"teacher_id": ACCOUNT}

    id: str  # the code, upper case
    teacher_id: str
    # Copies kept for reading the collection directly (the account is the source of truth).
    teacher_username: str = ""
    teacher_name: str = ""
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


# --- subjects: teachers' folders, materials and quizzes (D42) ------------------------------------

SUBJECT = Ref("subjects", "cascade")
FOLDER = Ref("folders", "cascade")
RESOURCE = Ref("resources", "cascade")
QUIZ = Ref("quizzes", "cascade")
RESOURCE_KINDS = ("file", "link", "note")
QUESTION_KINDS = ("single", "multiple", "true_false", "short")


@dataclass(kw_only=True)
class Subject(Document):
    """A subject such as Java or DBMS. Teachers pick one or add a missing one."""

    __collection__ = "subjects"  # unique key

    id: int = 0
    key: str  # lower case name without extra spaces: "java" (merges "Java" and "java")
    name: str
    created_by: str | None = None  # account id; None for the starting list
    created_at: datetime = field(default_factory=now)


@dataclass(kw_only=True)
class Folder(Document):
    """One teacher's folder for one subject, e.g. "Java by Dr. Ravi Singh"."""

    __collection__ = "folders"  # unique (subject_id, teacher_id)
    __refs__: ClassVar[Mapping[str, Ref]] = {"subject_id": SUBJECT, "teacher_id": ACCOUNT}

    id: int = 0
    subject_id: int
    teacher_id: str
    about: str = ""
    created_at: datetime = field(default_factory=now)


@dataclass(kw_only=True)
class Enrollment(Document):
    __collection__ = "enrollments"  # unique (folder_id, student_id)
    __refs__: ClassVar[Mapping[str, Ref]] = {"folder_id": FOLDER, "student_id": ACCOUNT}

    id: int = 0
    folder_id: int
    student_id: str
    created_at: datetime = field(default_factory=now)


@dataclass(kw_only=True)
class Resource(Document):
    """Study material in a folder: an uploaded file, a link, or a typed note."""

    __collection__ = "resources"
    __refs__: ClassVar[Mapping[str, Ref]] = {"folder_id": FOLDER}

    id: int = 0
    folder_id: int
    kind: str
    title: str
    description: str = ""
    url: str | None = None  # link
    text: str | None = None  # note
    file_name: str | None = None  # file
    content_type: str | None = None
    size: int = 0  # bytes stored (files)
    created_at: datetime = field(default_factory=now)

    def validate(self) -> None:
        one_of(self.kind, RESOURCE_KINDS, "kind")


@dataclass(kw_only=True)
class ResourceChunk(Document):
    """Part of an uploaded file (files are split so no document nears MongoDB's 16 MB cap)."""

    __collection__ = "resource_chunks"  # (resource_id, n)
    __id_kind__: ClassVar[IdKind] = "given"
    __refs__: ClassVar[Mapping[str, Ref]] = {"resource_id": RESOURCE}

    id: str  # "<resource id>:<n>"
    resource_id: int
    n: int
    data: bytes


@dataclass(kw_only=True)
class Quiz(Document):
    """A teacher's quiz or assessment. Questions are embedded: {id, kind, text, options,
    answer (option indexes, or accepted texts for short answers), points, topic}."""

    __collection__ = "quizzes"
    __refs__: ClassVar[Mapping[str, Ref]] = {"folder_id": FOLDER}

    id: int = 0
    folder_id: int
    title: str
    description: str = ""
    questions: list[dict[str, Any]] = field(default_factory=list)
    time_limit_min: int | None = None
    max_attempts: int = 1
    show_answers: bool = True  # after submitting
    published: bool = False
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)

    def validate(self) -> None:
        check(self.max_attempts >= 1, "max_attempts must be at least 1")
        for q in self.questions:
            one_of(q.get("kind", ""), QUESTION_KINDS, "question kind")


@dataclass(kw_only=True)
class QuizAttempt(Document):
    """A student's submitted answers. ``results`` holds one {id, correct, points} per question."""

    __collection__ = "quiz_attempts"  # (quiz_id, student_id)
    __refs__: ClassVar[Mapping[str, Ref]] = {"quiz_id": QUIZ, "student_id": ACCOUNT}

    id: int = 0
    quiz_id: int
    student_id: str
    answers: dict[str, Any] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    score: float = 0.0
    max_score: float = 0.0
    started_at: datetime = field(default_factory=now)
    submitted_at: datetime | None = None
    late: bool = False  # submitted after the time limit


# --- question banks and adaptive practice (D43) --------------------------------------------------


@dataclass(kw_only=True)
class BankQuestion(Document):
    """A multiple-choice question in a subject's question bank: a Mentora starter question
    (``seed_key`` set) or one written by a teacher of the subject."""

    __collection__ = "bank_questions"  # (subject_id, topic); seed_key
    __refs__: ClassVar[Mapping[str, Ref]] = {
        "subject_id": SUBJECT,
        "author_id": Ref("accounts", "set_null"),
    }

    id: int = 0
    subject_id: int
    topic: str
    text: str
    options: list[str] = field(default_factory=list)
    answer: int = 0  # index into options
    explanation: str = ""
    difficulty: int = 2  # 1 easy, 2 medium, 3 hard
    seed_key: str | None = None  # starter questions: "<subject key>:<hash of the text>"
    author_id: str | None = None
    edited: bool = False  # a starter question changed by a teacher (the seed never overwrites it)
    hidden: bool = False
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)

    def validate(self) -> None:
        check(2 <= len(self.options) <= 6, "a question needs 2-6 options")
        check(0 <= self.answer < len(self.options), "the answer must be one of the options")
        check(self.difficulty in (1, 2, 3), "difficulty is 1, 2 or 3")


@dataclass(kw_only=True)
class PracticeRound(Document):
    """A student's round of practice questions in one subject, picked for their weak topics.
    ``plan`` is [{id, topic, reason}]; ``results`` is [{id, topic, choice, correct, at}]."""

    __collection__ = "practice_rounds"  # (student_id, subject_id)
    __refs__: ClassVar[Mapping[str, Ref]] = {"student_id": ACCOUNT, "subject_id": SUBJECT}

    id: int = 0
    student_id: str
    subject_id: int
    plan: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    focus: list[str] = field(default_factory=list)  # the weak topics this round aims at
    score: int = 0
    total: int = 0
    started_at: datetime = field(default_factory=now)
    finished_at: datetime | None = None


# --- learning roadmaps (D44) ---------------------------------------------------------------------


@dataclass(kw_only=True)
class Roadmap(Document):
    """A student's week-by-week plan for a goal such as "Learn Java from basic to advanced".
    ``weeks`` is [{n, title, stage, topics, tasks: [{id, kind, text, topics, done, ...}]}];
    ``adaptations`` is [{key, at, text}], the changes Mentora made and why."""

    __collection__ = "roadmaps"  # (student_id, status)
    __refs__: ClassVar[Mapping[str, Ref]] = {
        "student_id": ACCOUNT,
        "subject_id": Ref("subjects", "set_null"),
    }

    id: int = 0
    student_id: str
    goal: str
    subject: str
    subject_id: int | None = None
    level: str = "beginner"
    pace: str = "steady"
    source: str = "curated"  # curated template, or written by the AI model
    weeks: list[dict[str, Any]] = field(default_factory=list)
    adaptations: list[dict[str, Any]] = field(default_factory=list)
    status: str = "active"
    start_date: datetime = field(default_factory=now)
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)
    completed_at: datetime | None = None

    def validate(self) -> None:
        one_of(self.status, ("active", "completed", "archived"), "status")
        one_of(self.level, ("beginner", "some", "experienced"), "level")
        one_of(self.pace, ("steady", "fast"), "pace")


# --- AI tutor chat (D46) -------------------------------------------------------------------------


@dataclass(kw_only=True)
class ChatThread(Document):
    """A student's conversation with the AI tutor chat; ``messages`` is [{role, text, at}]."""

    __collection__ = "chat_threads"  # (student_id, updated_at)
    __refs__: ClassVar[Mapping[str, Ref]] = {"student_id": ACCOUNT}

    id: int = 0
    student_id: str
    title: str = "New chat"
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)


# --- customer support (D49) -----------------------------------------------------------------------

SUPPORT_CATEGORIES = ("bug", "account", "content", "ai_tutor", "teacher", "other")


@dataclass(kw_only=True)
class SupportTicket(Document):
    """A complaint or problem report raised from the Customer support page; it is also emailed
    to the Mentora support inbox (reply-to the user)."""

    __collection__ = "support_tickets"  # (account_id, created_at)
    __refs__: ClassVar[Mapping[str, Ref]] = {"account_id": ACCOUNT}

    id: int = 0
    account_id: str
    category: str
    subject: str
    message: str
    page: str = ""  # where in Mentora it happened (optional)
    priority: str = "normal"  # normal | high (it stops the user from studying)
    status: str = "open"
    emailed: bool = False
    created_at: datetime = field(default_factory=now)
    # Support resolves a request from the link in its email; only the token's hash is stored.
    resolve_token: str | None = None
    resolution: str = ""  # what was fixed, sent to the user
    resolved_at: datetime | None = None
    reopened: int = 0

    def validate(self) -> None:
        one_of(self.category, SUPPORT_CATEGORIES, "category")
        one_of(self.status, ("open", "resolved"), "status")
        one_of(self.priority, ("normal", "high"), "priority")

    @property
    def number(self) -> str:
        return f"MEN-{self.id:05d}"


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
    Subject,
    Folder,
    Enrollment,
    Resource,
    ResourceChunk,
    Quiz,
    QuizAttempt,
    BankQuestion,
    PracticeRound,
    Roadmap,
    ChatThread,
    SupportTicket,
)
BY_COLLECTION: dict[str, type[Document]] = {model.__collection__: model for model in MODELS}
