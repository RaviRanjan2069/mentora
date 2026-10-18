"""xAPI statements for every learner, LMS and tutor event (design rule 3).

Tutor actions carry a ``tutor-action`` context extension with the policy version, the
(agent, move, style) action, its propensity mu(a|s), the filter outcome, retrieved passage
ids and the escalation flag. Offline RL and off-policy evaluation read these fields.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

XAPI_BASE = "https://mentora.example/xapi"  # placeholder IRI root, see docs/decisions.md D6

EXT_TUTOR_ACTION = f"{XAPI_BASE}/extensions/tutor-action"
EXT_TURN = f"{XAPI_BASE}/extensions/turn"
EXT_COURSE = f"{XAPI_BASE}/extensions/course"
EXT_CONFIDENCE = f"{XAPI_BASE}/extensions/confidence"
EXT_TACTIC = f"{XAPI_BASE}/extensions/tactic"
EXT_HINTS = f"{XAPI_BASE}/extensions/hints-used"
EXT_ATTEMPT = f"{XAPI_BASE}/extensions/attempt"
EXT_SRL_TAGS = f"{XAPI_BASE}/extensions/srl-tags"
EXT_LEARNER_INITIATED = f"{XAPI_BASE}/extensions/learner-initiated"

_ADL = "http://adlnet.gov/expapi/verbs"
VERBS: dict[str, str] = {
    "launched": f"{_ADL}/launched",
    "initialized": f"{_ADL}/initialized",
    "terminated": f"{_ADL}/terminated",
    "experienced": f"{_ADL}/experienced",
    "answered": f"{_ADL}/answered",
    "asked": f"{_ADL}/asked",
    "commented": f"{_ADL}/commented",
    "received": f"{XAPI_BASE}/verbs/received",  # learner received a tutor action
}

SpecialMove = Literal["WAIT", "ESCALATE"]
SPECIAL_MOVES: frozenset[str] = frozenset({"WAIT", "ESCALATE"})


class _XModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)


class Account(_XModel):
    homePage: str
    name: str


class Actor(_XModel):
    objectType: Literal["Agent"] = "Agent"
    account: Account


class Verb(_XModel):
    id: str
    display: dict[str, str]


class ActivityDefinition(_XModel):
    name: dict[str, str] | None = None
    type: str | None = None
    extensions: dict[str, Any] | None = None


class Activity(_XModel):
    objectType: Literal["Activity"] = "Activity"
    id: str
    definition: ActivityDefinition | None = None


class Score(_XModel):
    scaled: float | None = Field(default=None, ge=-1.0, le=1.0)
    raw: float | None = None
    min: float | None = None
    max: float | None = None


class Result(_XModel):
    score: Score | None = None
    success: bool | None = None
    completion: bool | None = None
    response: str | None = None
    duration: str | None = None  # ISO 8601 duration
    extensions: dict[str, Any] | None = None


class Context(_XModel):
    registration: str | None = None  # session id
    platform: str = "Mentora"
    extensions: dict[str, Any] = Field(default_factory=dict)


class ActionRef(_XModel):
    """A catalogue action (agent, move, style), or the special WAIT / ESCALATE moves."""

    agent: str | None = None
    move: str
    style: Literal["Socratic", "Directive"] | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        special = self.move in SPECIAL_MOVES
        if special and (self.agent is not None or self.style is not None):
            raise ValueError(f"{self.move} takes no agent or style")
        if not special and (self.agent is None or self.style is None):
            raise ValueError("catalogue actions need both agent and style")
        return self

    @property
    def id(self) -> str:
        return self.move if self.move in SPECIAL_MOVES else f"{self.agent}.{self.move}.{self.style}"


class FilterOutcome(_XModel):
    """What the deterministic safety filter allowed, and what it removed and why."""

    feasible_action_ids: list[str] = Field(min_length=1)
    removed: dict[str, list[str]] = Field(default_factory=dict)  # constraint -> action ids


class TutorActionExtension(_XModel):
    policy_version: str
    action: ActionRef
    propensity: float = Field(gt=0.0, le=1.0)
    filter_outcome: FilterOutcome
    retrieved_passage_ids: list[str] = Field(default_factory=list)
    escalated: bool = False
    prompt_version: str | None = None
    model: str | None = None
    # Full behaviour-policy distribution over F(s) (for audits and off-policy evaluation).
    action_probs: dict[str, float] | None = None
    memory_item_ids: list[int] = Field(default_factory=list)
    decision_reason: str | None = None  # why the policy chose this action (teacher console)

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if self.action.id not in self.filter_outcome.feasible_action_ids:
            raise ValueError(f"action {self.action.id} is outside the feasible set F(s)")
        if self.action.move == "ESCALATE" and not self.escalated:
            raise ValueError("ESCALATE action must set escalated=True")
        if self.action_probs is not None:
            if set(self.action_probs) - set(self.filter_outcome.feasible_action_ids):
                raise ValueError("action_probs puts mass outside F(s)")
            if abs(sum(self.action_probs.values()) - 1.0) > 1e-6:
                raise ValueError("action_probs must sum to 1")
            if abs(self.action_probs.get(self.action.id, 0.0) - self.propensity) > 1e-9:
                raise ValueError("propensity must equal action_probs[action]")
        return self


class Statement(_XModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    actor: Actor
    verb: Verb
    object_: Activity = Field(alias="object")
    result: Result | None = None
    context: Context = Field(default_factory=Context)
    timestamp: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def learner_id(self) -> str:
        return self.actor.account.name

    @property
    def session_id(self) -> str | None:
        return self.context.registration

    @property
    def turn(self) -> int | None:
        value = self.context.extensions.get(EXT_TURN)
        return int(value) if value is not None else None

    @property
    def item_id(self) -> int | None:
        prefix = f"{XAPI_BASE}/items/"
        oid = self.object_.id
        return int(oid[len(prefix) :]) if oid.startswith(prefix) else None

    @property
    def tutor_action(self) -> TutorActionExtension | None:
        raw = self.context.extensions.get(EXT_TUTOR_ACTION)
        return TutorActionExtension.model_validate(raw) if raw is not None else None

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


# --- builders --------------------------------------------------------------------------


def _actor(learner_id: str) -> Actor:
    return Actor(account=Account(homePage=XAPI_BASE, name=learner_id))


def _verb(name: str) -> Verb:
    return Verb(id=VERBS[name], display={"en-US": name})


def _context(session_id: str | None, turn: int | None, **ext: Any) -> Context:
    extensions: dict[str, Any] = {k: v for k, v in ext.items() if v is not None}
    if turn is not None:
        extensions[EXT_TURN] = turn
    return Context(registration=session_id, extensions=extensions)


def learner_message(
    learner_id: str,
    session_id: str,
    turn: int,
    text: str,
    timestamp: datetime | None = None,
    srl_tags: dict[str, bool] | None = None,
) -> Statement:
    extensions = {EXT_SRL_TAGS: srl_tags} if srl_tags is not None else None
    return Statement(
        actor=_actor(learner_id),
        verb=_verb("commented"),
        object_=Activity(id=f"{XAPI_BASE}/sessions/{session_id}/chat"),
        result=Result(response=text, extensions=extensions),
        context=_context(session_id, turn),
        timestamp=timestamp or datetime.now(UTC),
    )


def lms_event(
    learner_id: str,
    session_id: str | None,
    turn: int | None,
    verb: str,
    object_id: str,
    name: str | None = None,
    timestamp: datetime | None = None,
) -> Statement:
    """A learner/LMS event such as opening course material ("experienced") or a session
    starting ("initialized") or ending ("terminated")."""
    definition = ActivityDefinition(name={"en-US": name}) if name else None
    return Statement(
        actor=_actor(learner_id),
        verb=_verb(verb),
        object_=Activity(id=object_id, definition=definition),
        context=_context(session_id, turn),
        timestamp=timestamp or datetime.now(UTC),
    )


def quiz_answer(
    learner_id: str,
    session_id: str,
    turn: int,
    item_id: int,
    response: str,
    success: bool,
    confidence: float | None = None,
    timestamp: datetime | None = None,
    response_seconds: float | None = None,
    hints_used: int = 0,
    attempt: int = 1,
) -> Statement:
    extensions: dict[str, Any] = {EXT_HINTS: hints_used, EXT_ATTEMPT: attempt}
    if confidence is not None:
        extensions[EXT_CONFIDENCE] = confidence
    duration = f"PT{response_seconds:.1f}S" if response_seconds is not None else None
    return Statement(
        actor=_actor(learner_id),
        verb=_verb("answered"),
        object_=Activity(id=f"{XAPI_BASE}/items/{item_id}"),
        result=Result(response=response, success=success, duration=duration, extensions=extensions),
        context=_context(session_id, turn),
        timestamp=timestamp or datetime.now(UTC),
    )


def tutor_action(
    learner_id: str,
    session_id: str,
    turn: int,
    extension: TutorActionExtension,
    reply_text: str | None,
    timestamp: datetime | None = None,
) -> Statement:
    """Log a tutor decision. ``reply_text`` is None for a silent WAIT."""
    return Statement(
        actor=_actor(learner_id),
        verb=_verb("received"),
        object_=Activity(id=f"{XAPI_BASE}/actions/{extension.action.id}"),
        result=Result(response=reply_text) if reply_text is not None else None,
        context=_context(session_id, turn, **{EXT_TUTOR_ACTION: extension.model_dump(mode="json")}),
        timestamp=timestamp or datetime.now(UTC),
    )
