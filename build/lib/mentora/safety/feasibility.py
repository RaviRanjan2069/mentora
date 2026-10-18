"""The deterministic safety and feasibility filter F(s) (design rule 2).

Pure Python, never an LLM. Every policy, in every mode, chooses only from the set this
returns. Constraints, applied in this order:

1. well-being: distress detected -> only ESCALATE (support resources are shown)
2. integrity:   graded item -> no worked_example, no Directive style
3. prerequisites: no practice_item if prerequisite mastery < theta_pre
4. load:        at most n_max unsolicited interventions per window
5. teacher rules from the database

WAIT and ESCALATE are never removed by constraints 2-5, so the set is never empty.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from mentora.config.settings import SafetySettings
from mentora.logging_xapi.statements import ActionRef, FilterOutcome
from mentora.policy.catalogue import ESCALATE, WAIT, Catalogue, Phase
from mentora.safety.teacher_rules import TeacherRuleSpec

ALWAYS_AVAILABLE = frozenset({WAIT.id, ESCALATE.id})


@dataclass(frozen=True)
class FilterContext:
    """Everything the filter needs, computed by the caller from the learner model,
    the concept graph and the event log."""

    now: datetime
    distress: bool = False
    graded_item: bool = False
    # Lowest mastery among the prerequisites of the practice target; None = no prerequisites.
    prereq_mastery: float | None = None
    recent_unsolicited: Sequence[datetime] = ()
    week: int | None = None
    phase: Phase | None = None


@dataclass(frozen=True)
class FilterResult:
    feasible: frozenset[ActionRef]
    removed: dict[str, list[str]] = field(default_factory=dict)
    show_support_resources: bool = False

    def feasible_ids(self) -> list[str]:
        return sorted(a.id for a in self.feasible)

    def allows(self, action: ActionRef) -> bool:
        return action in self.feasible

    def to_outcome(self) -> FilterOutcome:
        return FilterOutcome(feasible_action_ids=self.feasible_ids(), removed=self.removed)


def unsolicited_in_window(ctx: FilterContext, window_minutes: int) -> int:
    start = ctx.now - timedelta(minutes=window_minutes)
    return sum(1 for t in ctx.recent_unsolicited if start < t <= ctx.now)


def feasible_set(
    ctx: FilterContext,
    rules: Sequence[TeacherRuleSpec],
    *,
    catalogue: Catalogue,
    settings: SafetySettings,
) -> FilterResult:
    all_actions = list(catalogue)

    if ctx.distress:
        others = sorted(a.id for a in all_actions if a.id != ESCALATE.id)
        return FilterResult(frozenset({ESCALATE}), {"wellbeing": others}, True)

    feasible = {a.id: a for a in all_actions}
    removed: dict[str, list[str]] = {}

    def drop(constraint: str, predicate: Callable[[ActionRef], bool]) -> None:
        hits = sorted(
            aid for aid, a in feasible.items() if aid not in ALWAYS_AVAILABLE and predicate(a)
        )
        for aid in hits:
            del feasible[aid]
        if hits:  # merge: two teacher rules may share a name
            removed[constraint] = sorted({*removed.get(constraint, []), *hits})

    if ctx.graded_item:
        drop("integrity", lambda a: a.move == "worked_example" or a.style == "Directive")

    if ctx.prereq_mastery is not None and ctx.prereq_mastery < settings.theta_pre:
        drop("prerequisites", lambda a: a.move == "practice_item")

    if unsolicited_in_window(ctx, settings.window_minutes) >= settings.n_max:
        drop("load", catalogue.is_unsolicited)

    for rule in rules:
        if rule.when.holds(week=ctx.week, graded=ctx.graded_item, phase=ctx.phase):
            drop(f"teacher_rule:{rule.name}", rule.forbid.matches)

    return FilterResult(frozenset(feasible.values()), removed)
