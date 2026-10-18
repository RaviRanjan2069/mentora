"""Policy interfaces. A policy sees only structured observations (numeric state plus
categorical flags), never free text, and always chooses inside the feasible set F(s)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mentora.learner_model.requests import Request
from mentora.logging_xapi.statements import ActionRef
from mentora.policy.catalogue import Phase
from mentora.safety.feasibility import FilterResult


@dataclass(frozen=True)
class PolicyObs:
    state: tuple[float, ...]
    phase: Phase
    session_start: bool
    has_active_goal: bool
    has_plan: bool
    consecutive_wrong: int
    just_assessed: bool
    quiz_completed: bool
    task_active: bool
    graded_item: bool
    item_just_presented: bool
    confidence_due: bool
    request: Request


@dataclass(frozen=True)
class Preference:
    action: ActionRef
    reason: str


@dataclass(frozen=True)
class Decision:
    action: ActionRef
    propensity: float  # mu(a|s) under the policy that acted
    probs: dict[str, float]  # full distribution over F(s)
    reason: str
    policy_version: str


class Proposer(Protocol):
    """Something that names a preferred action inside F(s) (rule set or learned Q)."""

    version: str

    def prefer(self, obs: PolicyObs, allowed: FilterResult) -> Preference: ...
