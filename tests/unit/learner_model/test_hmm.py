"""M4 'done when': our online forward filter matches hmmlearn."""

from __future__ import annotations

import numpy as np
import pytest
from hmmlearn.hmm import CategoricalHMM
from hypothesis import given, settings
from hypothesis import strategies as st

from mentora.learner_model.hmm_tactics import TacticHMM, fit_tactic_hmm


def _random_model(h: int, seed: int) -> CategoricalHMM:
    rng = np.random.default_rng(seed)
    m = CategoricalHMM(n_components=h, n_features=6)
    m.startprob_ = rng.dirichlet(np.ones(h))
    m.transmat_ = rng.dirichlet(np.ones(h), size=h)
    m.emissionprob_ = rng.dirichlet(np.ones(6), size=h)
    return m


@settings(max_examples=60, deadline=None)
@given(
    h=st.integers(1, 6),
    seed=st.integers(0, 10_000),
    obs=st.lists(st.integers(0, 5), min_size=1, max_size=40),
)
def test_forward_filter_matches_hmmlearn(h: int, seed: int, obs: list[int]) -> None:
    ref = _random_model(h, seed)
    ours = TacticHMM(ref.startprob_, ref.transmat_, ref.emissionprob_)
    alphas = ours.filter(obs)
    for t in range(len(obs)):
        prefix = np.asarray(obs[: t + 1]).reshape(-1, 1)
        # The smoothed posterior at the last step of a prefix equals the filtered alpha_t.
        expected = ref.predict_proba(prefix)[-1]
        np.testing.assert_allclose(alphas[t], expected, atol=1e-8)
    assert np.allclose(alphas.sum(axis=1), 1.0)


def test_bic_selects_from_range_and_recovers_structure() -> None:
    gen = _random_model(3, 1)
    gen.emissionprob_ = np.array(
        [
            [0.7, 0.1, 0.05, 0.05, 0.05, 0.05],
            [0.05, 0.05, 0.7, 0.1, 0.05, 0.05],
            [0.05, 0.05, 0.05, 0.05, 0.1, 0.7],
        ]
    )
    gen.transmat_ = np.array([[0.85, 0.1, 0.05], [0.05, 0.85, 0.1], [0.1, 0.05, 0.85]])
    seqs = [gen.sample(60, random_state=i)[0].ravel().tolist() for i in range(80)]
    hmm, bic = fit_tactic_hmm(seqs, 2, 5, 100, seed=0)
    assert set(bic) == {2, 3, 4, 5}
    assert hmm.n_states == min(bic, key=lambda k: bic[k])
    assert hmm.n_states == 3


def test_uninformed_and_json_roundtrip(tmp_path: pytest.TempPathFactory) -> None:
    u = TacticHMM.uninformed()
    assert u.filter([0, 3, 5]).tolist() == [[1.0], [1.0], [1.0]]
    ref = _random_model(4, 9)
    hmm = TacticHMM(ref.startprob_, ref.transmat_, ref.emissionprob_)
    back = TacticHMM.from_json(hmm.to_json())
    np.testing.assert_allclose(back.filter([1, 2, 3]), hmm.filter([1, 2, 3]))
