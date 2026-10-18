"""M3 'done when': property tests show zero filter violations across randomized states.

Each constraint is re-stated independently below (``violations``) and checked against the
filter for thousands of random contexts, settings and teacher rules, in both directions:
nothing feasible violates a constraint (safety), and nothing is removed without a reason
(the filter is not over-restrictive).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from mentora.config import get_settings
from mentora.config.settings import SafetySettings
from mentora.logging_xapi.statements import ActionRef
from mentora.policy.catalogue import AGENTS, ESCALATE, WAIT, default_catalogue
from mentora.safety.feasibility import FilterContext, feasible_set
from mentora.safety.teacher_rules import Forbid, TeacherRuleSpec, When

CAT = default_catalogue()
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
BASE = get_settings().safety
ALL = list(CAT)


@st.composite
def safety_settings(draw: st.DrawFn) -> SafetySettings:
    return BASE.model_copy(
        update={
            "theta_pre": draw(st.floats(0.0, 1.0)),
            "n_max": draw(st.integers(0, 5)),
            "window_minutes": draw(st.integers(1, 60)),
        }
    )


@st.composite
def contexts(draw: st.DrawFn) -> FilterContext:
    offsets = draw(st.lists(st.integers(-90, 5), max_size=8))  # minutes; >0 is in the future
    return FilterContext(
        now=NOW,
        distress=draw(st.booleans()),
        graded_item=draw(st.booleans()),
        prereq_mastery=draw(st.none() | st.floats(0.0, 1.0)),
        recent_unsolicited=[NOW + timedelta(minutes=o) for o in offsets],
        week=draw(st.none() | st.integers(1, 14)),
        phase=draw(st.none() | st.sampled_from(["forethought", "performance", "reflection"])),
    )


@st.composite
def rules(draw: st.DrawFn) -> TeacherRuleSpec:
    kind = draw(st.sampled_from(["agent", "move", "style", "action"]))
    value = {
        "agent": st.sampled_from(AGENTS),
        "move": st.sampled_from(sorted(CAT.moves)),
        "style": st.sampled_from(["Socratic", "Directive"]),
        "action": st.sampled_from([a.id for a in ALL]),  # includes WAIT / ESCALATE
    }[kind]
    when = When(
        week_lte=draw(st.none() | st.integers(1, 14)),
        week_gte=draw(st.none() | st.integers(1, 14)),
        graded=draw(st.none() | st.booleans()),
        phase=draw(st.none() | st.sampled_from(["forethought", "performance", "reflection"])),
    )
    return TeacherRuleSpec(
        name=f"r{draw(st.integers(0, 999))}", forbid=Forbid(**{kind: draw(value)}), when=when
    )


def violations(
    a: ActionRef, ctx: FilterContext, rs: list[TeacherRuleSpec], s: SafetySettings
) -> set[str]:
    """Independent statement of the five constraints."""
    out: set[str] = set()
    if ctx.distress and a != ESCALATE:
        out.add("wellbeing")
    if a in (WAIT, ESCALATE):
        return out
    if ctx.graded_item and (a.move == "worked_example" or a.style == "Directive"):
        out.add("integrity")
    mastery = ctx.prereq_mastery
    if a.move == "practice_item" and mastery is not None and mastery < s.theta_pre:
        out.add("prerequisites")
    window_start = ctx.now - timedelta(minutes=s.window_minutes)
    recent = [t for t in ctx.recent_unsolicited if window_start < t <= ctx.now]
    spec = CAT.spec(a)
    if spec and spec.unsolicited and len(recent) >= s.n_max:
        out.add("load")
    for r in rs:
        applies = (
            (r.when.week_lte is None or (ctx.week is not None and ctx.week <= r.when.week_lte))
            and (r.when.week_gte is None or (ctx.week is not None and ctx.week >= r.when.week_gte))
            and (r.when.graded is None or ctx.graded_item == r.when.graded)
            and (r.when.phase is None or ctx.phase == r.when.phase)
        )
        f = r.forbid
        hit = (
            (f.agent is None or a.agent == f.agent)
            and (f.move is None or a.move == f.move)
            and (f.style is None or a.style == f.style)
            and (f.action is None or a.id == f.action)
        )
        if applies and hit:
            out.add(f"teacher_rule:{r.name}")
    return out


@settings(max_examples=3000, deadline=None)
@given(contexts(), st.lists(rules(), max_size=4), safety_settings())
def test_zero_violations_and_no_overblocking(
    ctx: FilterContext, rs: list[TeacherRuleSpec], s: SafetySettings
) -> None:
    result = feasible_set(ctx, rs, catalogue=CAT, settings=s)
    for a in ALL:
        v = violations(a, ctx, rs, s)
        if a in result.feasible:
            assert not v, f"{a.id} is feasible but violates {v}"
        else:
            assert v, f"{a.id} was removed without any violated constraint"


@settings(max_examples=1500, deadline=None)
@given(contexts(), st.lists(rules(), max_size=4), safety_settings())
def test_structural_guarantees(
    ctx: FilterContext, rs: list[TeacherRuleSpec], s: SafetySettings
) -> None:
    result = feasible_set(ctx, rs, catalogue=CAT, settings=s)
    assert result.feasible, "F(s) is never empty"
    assert ESCALATE in result.feasible, "ESCALATE is always available"
    assert result.feasible <= set(ALL), "only catalogue actions"
    if ctx.distress:
        assert result.feasible == {ESCALATE} and result.show_support_resources
    else:
        assert WAIT in result.feasible and not result.show_support_resources
        removed = {aid for ids in result.removed.values() for aid in ids}
        assert removed.isdisjoint(result.feasible_ids())
        assert removed | set(result.feasible_ids()) == {a.id for a in ALL}
    # Deterministic: same input, same output.
    again = feasible_set(ctx, rs, catalogue=CAT, settings=s)
    assert again == result
    outcome = result.to_outcome()
    assert outcome.feasible_action_ids == result.feasible_ids()
