"""M8 'done when': on synthetic logs, training is reproducible, the policy never leaves F(s),
and the gate either registers a candidate or records why the rule policy stays."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mentora.config import get_settings
from mentora.db import StoreFactory
from mentora.db import models as m
from mentora.offline.fairness import fairness_check
from mentora.offline.ope_dr import OPEResult, evaluate, rule_target
from mentora.offline.policies import CQLEnsemble, TabularQ
from mentora.offline.train import run_offline_pipeline, train_candidate
from mentora.policy import registry
from mentora.policy.catalogue import ESCALATE, default_catalogue
from mentora.reward.dataset_builder import Dataset, Episode, Step, split_by_learner

from .conftest import offline_settings

CAT = default_catalogue()


# --- dataset ----------------------------------------------------------------------------


def test_dataset_from_logs(dataset: Dataset) -> None:
    assert len(dataset.episodes) == 36 and len(dataset.learners) == 12
    assert dataset.n_actions == len(CAT) and dataset.state_dim == 28
    for ep in dataset.episodes:
        for cur, nxt in zip(ep.steps, ep.steps[1:], strict=False):
            assert cur.t + 1 == nxt.t and not cur.terminal
            assert np.array_equal(cur.next_feasible, nxt.feasible)  # type: ignore[arg-type]
            assert np.allclose(cur.next_state, nxt.state)
        assert ep.steps[-1].terminal
        for s in ep.steps:
            assert s.feasible[s.action] and 0 < s.propensity <= 1
            assert s.behaviour_probs.sum() == pytest.approx(1.0)
            assert not s.behaviour_probs[~s.feasible].any()  # no mass outside F(s)
    assert {g["gender"] for g in dataset.groups.values()} <= {"female", "male", "unknown"}


def test_split_is_by_learner(dataset: Dataset) -> None:
    train, val = split_by_learner(dataset, 0.25, seed=1)
    assert set(train.learners).isdisjoint(val.learners)
    assert len(train.episodes) + len(val.episodes) == len(dataset.episodes)


# --- policies ---------------------------------------------------------------------------


def test_ensemble_cql_is_reproducible_and_stays_in_feasible_set(
    dataset: Dataset, tmp_path: Path
) -> None:
    s = offline_settings(tmp_path)
    train, val = split_by_learner(dataset, 0.25, s.policy.seed)
    a = train_candidate(train, val, s, "cql_ensemble")
    b = train_candidate(train, val, s, "cql_ensemble")
    assert isinstance(a, CQLEnsemble) and isinstance(b, CQLEnsemble)
    assert len(a.nets) == s.policy.ensemble_m == 5
    for step in val.steps:
        assert np.allclose(a.values(step.state), b.values(step.state))  # reproducible
        assert step.feasible[a.act(step.state, step.feasible, step.graded)]  # inside F(s)
    a.save(tmp_path / "p.pt")
    c = CQLEnsemble.load(tmp_path / "p.pt")
    st0 = val.steps[0]
    assert np.allclose(a.values(st0.state), c.values(st0.state)) and c.tau_u == a.tau_u


@settings(max_examples=150, deadline=None)
@given(
    st.lists(st.booleans(), min_size=42, max_size=42).filter(any),
    st.booleans(),
    st.lists(st.floats(0, 1), min_size=28, max_size=28),
)
def test_learned_policies_never_leave_any_feasible_mask(
    mask: list[bool], graded: bool, state: list[float]
) -> None:
    model = _small_model()
    f = np.asarray(mask)
    assert f[model.act(np.asarray(state), f, graded)]


_CACHE: dict[str, CQLEnsemble] = {}


def _small_model() -> CQLEnsemble:
    if "m" not in _CACHE:
        import torch

        torch.manual_seed(0)
        from mentora.offline.policies import _mlp

        _CACHE["m"] = CQLEnsemble(
            [_mlp(28, 16, 42) for _ in range(3)],
            1.0,
            0.0,
            [a.id for a in CAT].index(ESCALATE.id),
            {},
        )
    return _CACHE["m"]


def test_uncertain_graded_step_escalates() -> None:
    model = _small_model()  # tau_u = 0: any disagreement counts as uncertain
    f = np.ones(42, bool)
    s = np.full(28, 0.5)
    assert model.act(s, f, graded=True) == model.escalate_index


def test_tabular_baseline(dataset: Dataset, tmp_path: Path) -> None:
    s = offline_settings(tmp_path)
    model = TabularQ.fit(dataset, s.policy, s.offline)
    for step in dataset.steps:
        assert step.feasible[model.act(step.state, step.feasible, step.graded)]
    model.save(tmp_path / "t.json")
    again = TabularQ.load(tmp_path / "t.json")
    assert np.allclose(again.q, model.q)


# --- OPE and fairness ------------------------------------------------------------------------


def _bandit(n: int, seed: int) -> Dataset:
    """One-step episodes; behaviour picks action 0 or 1 with probability 0.5 each;
    action 0 pays 1, action 1 pays 0. True value: pi=0 -> 1, pi=1 -> 0."""
    rng = np.random.default_rng(seed)
    eps = []
    feasible = np.zeros(42, bool)
    feasible[:2] = True
    probs = np.zeros(42)
    probs[:2] = 0.5
    for i in range(n):
        a = int(rng.integers(0, 2))
        s = rng.random(28)
        step = Step(
            f"s{i}", f"l{i % 20}", 0, s, a, 0.5, 1.0 - a, s, feasible, probs, False, terminal=True
        )
        eps.append(Episode(f"s{i}", f"l{i % 20}", [step]))
    groups = {
        f"l{j}": {"gender": "female" if j % 2 else "male", "prior_tercile": "unknown"}
        for j in range(20)
    }
    return Dataset([a.id for a in CAT], eps, groups)


def _ope(data: Dataset, pi: object) -> OPEResult:
    return evaluate(
        data,
        pi,
        gamma=0.95,
        clip=20,
        iterations=5,
        alpha=1.0,
        bootstrap=200,  # type: ignore[arg-type]
        lcb_alpha=0.05,
        seed=0,
    )


def test_doubly_robust_recovers_known_values() -> None:
    data = _bandit(400, 0)
    good, bad = _ope(data, lambda s: 0), _ope(data, lambda s: 1)
    assert good.value == pytest.approx(1.0, abs=0.08) and bad.value == pytest.approx(0.0, abs=0.08)
    assert good.lcb <= good.value <= good.ucb and good.lcb > bad.ucb
    assert good.effective_sample_size > 100  # half the steps match the target


def test_rule_target_is_mode_of_behaviour(dataset: Dataset) -> None:
    for s in dataset.steps[:50]:
        assert s.behaviour_probs[rule_target(s)] == s.behaviour_probs.max()


def test_fairness_gap_check() -> None:
    data = _bandit(400, 1)
    cur = _ope(data, lambda s: 0)
    same = fairness_check(cur, cur, data, 5)
    assert same.ok and same.evaluable and "gender" in same.gaps
    # A candidate that is great for one gender and bad for the other widens the gap.
    unfair = OPEResult(
        cur.value,
        cur.lcb,
        cur.ucb,
        cur.n_episodes,
        1.0,
        1,
        np.asarray([1.0 if int(lr[1:]) % 2 else -1.0 for lr in cur.learners]),
        cur.learners,
    )
    assert not fairness_check(cur, unfair, data, 5).ok
    no_groups = Dataset(data.action_ids, data.episodes, {})
    report = fairness_check(cur, cur, no_groups, 5)
    assert not report.ok and not report.evaluable and "Not evaluable" in report.note


# --- the gate and the registry ---------------------------------------------------------------


def test_pipeline_gate_and_registry(sim_factory: StoreFactory, tmp_path: Path) -> None:
    s = offline_settings(tmp_path)
    r1 = run_offline_pipeline(s, sim_factory, data_label="simulation")
    assert r1.status in ("candidate", "rejected")
    assert r1.status == "candidate" or r1.reasons  # rejection always says why
    assert r1.metrics["simulation"]["violations"] == 0  # never leaves F(s) in simulation
    assert "simulation" in r1.report_markdown and "## Gate" in r1.report_markdown
    with sim_factory() as db:
        row = db.get(m.Policy, r1.version)
        assert row is not None and row.status == r1.status and row.reasons
        assert row.metrics["reward_weights"]["lambda_k"] == s.reward.lambda_k  # frozen weights
        assert registry.active_policy(db).version == "rule-v1"  # nothing changes automatically

    r2 = run_offline_pipeline(s, sim_factory, data_label="simulation", register=False)
    assert r2.metrics["ope_candidate"] == r1.metrics["ope_candidate"]  # reproducible
    assert r2.metrics["ope_current"] == r1.metrics["ope_current"]


def test_insufficient_data(session_factory: StoreFactory, tmp_path: Path) -> None:
    r = run_offline_pipeline(offline_settings(tmp_path), session_factory)
    assert r.status == "insufficient_data" and "current policy stays" in r.reasons[0]


def test_teacher_approval_activates_learned_policy(
    sim_factory: StoreFactory, dataset: Dataset, tmp_path: Path
) -> None:
    s = offline_settings(tmp_path)
    train, val = split_by_learner(dataset, 0.25, s.policy.seed)
    model = train_candidate(train, val, s, "tabular")
    path = tmp_path / "tab.json"
    model.save(path)
    with sim_factory.begin() as db:
        registry.register_candidate(
            db,
            "tabular-test",
            "tabular",
            {"model_path": str(path), "action_ids": dataset.action_ids},
            {},
            "test candidate",
        )
    with sim_factory.begin() as db:
        with pytest.raises(registry.RegistryError):
            registry.decide(db, "rule-v1", approve=True, teacher="t", note="x")
        registry.decide(db, "tabular-test", approve=True, teacher="lrn_teacher", note="ok")
    with sim_factory() as db:
        assert registry.active_policy(db).version == "tabular-test"
        assert db.get(m.Policy, "rule-v1").status == "retired"  # type: ignore[union-attr]

    from mentora.offline.simulator import run_simulation

    stats = run_simulation(
        get_settings(), sim_factory, n_sessions=4, turns=8, seed=99, policy_mode="deploy"
    )
    assert stats.violations == 0
    with sim_factory() as db:
        sids = db.distinct(m.Session, "id", {"learner_id": {"$regex": "^lrn_sim_99_"}})
        versions = set(db.distinct(m.Transition, "policy_version", {"session_id": {"$in": sids}}))
    assert versions == {"tabular-test/deploy"}  # the approved policy is live
