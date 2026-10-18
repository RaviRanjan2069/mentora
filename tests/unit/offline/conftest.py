from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from mentora.config import Settings, get_settings
from mentora.db import StoreFactory, connect
from mentora.db.client import drop_mock
from mentora.offline.simulator import run_simulation
from mentora.policy.catalogue import default_catalogue
from mentora.reward.dataset_builder import Dataset, build_dataset


def offline_settings(model_dir: Path) -> Settings:
    s = get_settings()
    return s.model_copy(
        update={
            "offline": s.offline.model_copy(
                update={
                    "epochs": 8,
                    "bootstrap": 60,
                    "sim_sessions": 6,
                    "sim_turns": 10,
                    "min_episodes": 10,
                    "fairness_min_group_episodes": 2,
                    "fqe_iterations": 8,
                }
            ),
            "learner_model": s.learner_model.model_copy(update={"model_dir": model_dir}),
        }
    )


@pytest.fixture(scope="module")
def sim_factory() -> Iterator[StoreFactory]:
    """Simulated logs (collect mode, with propensities): 36 sessions from 12 learners."""
    url = "mongomock://offline_sim"
    drop_mock(url)
    factory = connect(url)
    run_simulation(get_settings(), factory, n_sessions=36, turns=12, seed=21)
    yield factory
    drop_mock(url)


@pytest.fixture(scope="module")
def dataset(sim_factory: StoreFactory) -> Dataset:
    return build_dataset(sim_factory, default_catalogue())
