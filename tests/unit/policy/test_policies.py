from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mentora.config import get_settings
from mentora.policy.base import PolicyObs
from mentora.policy.catalogue import ESCALATE, WAIT, default_catalogue
from mentora.policy.collect import BehaviourPolicy, StateClusters, VisitCounts
from mentora.policy.rule_policy import RulePolicy
from mentora.safety.feasibility import FilterContext, feasible_set

CAT = default_catalogue()
SAFETY = get_settings().safety
NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
BASE = PolicyObs(
    state=(0.5,) * 28,
    phase="performance",
    session_start=False,
    has_active_goal=True,
    has_plan=True,
    consecutive_wrong=0,
    just_assessed=False,
    quiz_completed=False,
    task_active=False,
    graded_item=False,
    item_just_presented=False,
    confidence_due=False,
    request="none",
)


def _allowed(**kw: object):  # type: ignore[no-untyped-def]
    return feasible_set(FilterContext(now=NOW, **kw), [], catalogue=CAT, settings=SAFETY)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"session_start": True, "has_active_goal": False}, "Planner.elicit_smart_goal.Socratic"),
        ({"request": "plan", "has_plan": False}, "Planner.decompose_plan.Socratic"),
        ({"session_start": True}, "Planner.recall_past_goals.Socratic"),
        ({"quiz_completed": True}, "ReflectionCoach.socratic_reflection.Socratic"),
        ({"consecutive_wrong": 2}, "ContentTutor.graded_hint.Socratic"),
        ({"request": "answer"}, "ContentTutor.graded_hint.Socratic"),
        ({"request": "explanation"}, "ContentTutor.concept_explanation.Socratic"),
        (
            {"item_just_presented": True, "confidence_due": True},
            "Monitor.confidence_check.Socratic",
        ),
        ({}, "WAIT"),
        ({"request": "question"}, "WAIT"),
    ],
)
def test_rule_policy(changes: dict[str, object], expected: str) -> None:
    pref = RulePolicy(CAT).prefer(replace(BASE, **changes), _allowed())  # type: ignore[arg-type]
    assert pref.action.id == expected and pref.reason


def test_rule_policy_respects_filter() -> None:
    rp = RulePolicy(CAT)
    assert rp.prefer(BASE, _allowed(distress=True)).action == ESCALATE
    # Load limit reached: confidence_check (unsolicited) is not allowed -> WAIT.
    full = _allowed(recent_unsolicited=[NOW] * 3)
    obs = replace(BASE, item_just_presented=True, confidence_due=True)
    pref = rp.prefer(obs, full)
    assert pref.action == WAIT and "not allowed" in pref.reason


def test_deploy_mode_is_deterministic_with_propensity_one() -> None:
    pol = BehaviourPolicy(RulePolicy(CAT), mode="deploy", temperature=0.2, novelty_beta=0.1)
    d = pol.decide(replace(BASE, consecutive_wrong=3), _allowed(), random.Random(0))
    assert d.action.id == "ContentTutor.graded_hint.Socratic"
    assert d.propensity == 1.0 and d.probs == {d.action.id: 1.0}
    assert d.policy_version == "rule-v1/deploy"


@st.composite
def situations(draw: st.DrawFn) -> tuple[PolicyObs, object]:
    obs = replace(
        BASE,
        state=tuple(draw(st.lists(st.floats(0, 1), min_size=28, max_size=28))),
        session_start=draw(st.booleans()),
        has_active_goal=draw(st.booleans()),
        consecutive_wrong=draw(st.integers(0, 4)),
        quiz_completed=draw(st.booleans()),
        request=draw(
            st.sampled_from(["answer", "hint", "explanation", "plan", "question", "none"])
        ),
    )
    allowed = _allowed(
        distress=draw(st.booleans()),
        graded_item=draw(st.booleans()),
        prereq_mastery=draw(st.none() | st.floats(0, 1)),
        recent_unsolicited=[NOW] * draw(st.integers(0, 4)),
    )
    return obs, allowed


@settings(max_examples=400, deadline=None)
@given(situations(), st.integers(0, 10_000), st.floats(0.05, 2.0), st.floats(0, 1))
def test_collect_propensities_sum_to_one_inside_feasible_set(
    situation: tuple[PolicyObs, object], seed: int, temperature: float, beta: float
) -> None:
    obs, allowed = situation
    pol = BehaviourPolicy(
        RulePolicy(CAT), mode="collect", temperature=temperature, novelty_beta=beta
    )
    d = pol.decide(obs, allowed, random.Random(seed))  # type: ignore[arg-type]
    feasible = set(allowed.feasible_ids())  # type: ignore[attr-defined]
    # Exploration covers F(s) except ESCALATE, which is only ever the proposer's own choice.
    expected = feasible if d.action == ESCALATE else feasible - {ESCALATE.id}
    assert set(d.probs) == expected
    assert sum(d.probs.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(0.0 < p <= 1.0 for p in d.probs.values())
    assert 0.0 < d.propensity <= 1.0 and d.propensity == d.probs[d.action.id]
    assert d.action in allowed.feasible  # type: ignore[attr-defined]


def test_collect_centres_on_rule_choice_and_novelty_shifts_mass() -> None:
    allowed = _allowed()
    obs = replace(BASE, consecutive_wrong=2)
    pol = BehaviourPolicy(RulePolicy(CAT), mode="collect", temperature=0.2, novelty_beta=0.5)
    probs, _ = pol.distribution(obs, allowed)
    best = max(probs, key=lambda k: probs[k])
    assert best == "ContentTutor.graded_hint.Socratic" and probs[best] > 0.5
    counts = VisitCounts()
    for _ in range(50):
        counts.add(0, "Monitor.break_suggestion.Socratic")
    pol2 = BehaviourPolicy(
        RulePolicy(CAT), mode="collect", temperature=0.2, novelty_beta=0.5, counts=counts
    )
    probs2, _ = pol2.distribution(obs, allowed)
    assert probs2["Monitor.break_suggestion.Socratic"] < probs["Monitor.break_suggestion.Socratic"]


def test_same_seed_same_decision() -> None:
    allowed = _allowed()

    def make():
        return BehaviourPolicy(RulePolicy(CAT), mode="collect", temperature=1.0, novelty_beta=0.1)

    a = [make().decide(BASE, allowed, random.Random(s)).action.id for s in range(20)]
    b = [make().decide(BASE, allowed, random.Random(s)).action.id for s in range(20)]
    assert a == b and len(set(a)) > 1  # reproducible, and it does explore


def test_state_clusters(tmp_path: object) -> None:
    states = [[0.0, 0.0], [0.1, 0.0], [1.0, 1.0], [0.9, 1.0]]
    cl = StateClusters.fit(states, k=2, seed=0)
    assert cl.assign([0.05, 0.0]) != cl.assign([0.95, 1.0])
    assert StateClusters().assign([0.3, 0.3]) == 0


def test_collect_never_explores_into_escalate() -> None:
    pol = BehaviourPolicy(RulePolicy(CAT), mode="collect", temperature=5.0, novelty_beta=1.0)
    probs, _ = pol.distribution(BASE, _allowed())
    assert "ESCALATE" not in probs and "WAIT" in probs
    crisis, _ = pol.distribution(BASE, _allowed(distress=True))
    assert crisis == {"ESCALATE": 1.0}
