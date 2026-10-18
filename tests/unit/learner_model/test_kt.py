"""M4 'done when': the KT train script reports AUC for both models on a sample."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from mentora.config import get_settings
from mentora.config.settings import LearnerModelSettings
from mentora.course import CourseSpec, load_course
from mentora.learner_model.kt.data import (
    Interaction,
    load_assistments,
    synthetic_sequences,
    to_batch,
)
from mentora.learner_model.kt.mastery import CountMastery, make_mastery_model
from mentora.learner_model.kt.models import DKT, AKTStyle
from mentora.learner_model.kt.train import load_model, save_model, train_kt

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def course() -> CourseSpec:
    return load_course(ROOT / "data" / "concepts.yaml")


@pytest.fixture(scope="module")
def cfg() -> LearnerModelSettings:
    return get_settings().learner_model.model_copy(update={"kt_epochs": 6, "kt_hidden": 32})


@pytest.fixture(scope="module")
def seqs(course: CourseSpec) -> list[list[Interaction]]:
    return synthetic_sequences(course, 160, 40, seed=3)


@pytest.mark.parametrize("kind", ["dkt", "akt"])
def test_both_models_beat_chance_on_held_out_learners(
    kind: str, seqs: list[list[Interaction]], course: CourseSpec, cfg: LearnerModelSettings
) -> None:
    _, report = train_kt(kind, seqs, len(course.concepts), cfg)  # type: ignore[arg-type]
    assert report.n_test_learners == 32 and report.n_train_learners == 128
    assert report.test_auc > 0.65, report


def test_training_is_reproducible(
    seqs: list[list[Interaction]], course: CourseSpec, cfg: LearnerModelSettings
) -> None:
    small = cfg.model_copy(update={"kt_epochs": 2})
    _, a = train_kt("akt", seqs[:60], len(course.concepts), small)
    _, b = train_kt("akt", seqs[:60], len(course.concepts), small)
    assert a.test_auc == b.test_auc


@pytest.mark.parametrize("model", [DKT(20, 16), AKTStyle(20, 16, 4)])
def test_predictions_are_causal(model: DKT | AKTStyle, seqs: list[list[Interaction]]) -> None:
    """Changing future interactions must not change earlier predictions."""
    torch.manual_seed(0)
    seq = seqs[0][:12]
    altered = seq[:6] + [Interaction(x.concept, 1 - x.correct, 99.0, 1, 3) for x in seq[6:]]
    with torch.no_grad():
        p1 = model.predict_next(to_batch([seq]))[0, :5]
        p2 = model.predict_next(to_batch([altered]))[0, :5]
    assert torch.allclose(p1, p2)


def test_save_load_and_mastery(
    tmp_path: Path, seqs: list[list[Interaction]], course: CourseSpec, cfg: LearnerModelSettings
) -> None:
    model, report = train_kt(
        "dkt", seqs[:40], len(course.concepts), cfg.model_copy(update={"kt_epochs": 1})
    )
    path = save_model(model, report, tmp_path, cfg.kt_hidden, cfg.kt_heads)
    loaded = load_model(path)
    hist = seqs[1][:15]
    assert torch.allclose(model.mastery(hist), loaded.mastery(hist))
    for m in (loaded, AKTStyle(20, 16, 4)):
        k = m.mastery(hist)
        assert k.shape == (20,) and bool(((k >= 0) & (k <= 1)).all())
        assert m.mastery([]).shape == (20,)  # empty history works


def test_count_mastery_and_factory(cfg: LearnerModelSettings, tmp_path: Path) -> None:
    cm = CountMastery((1.0, 1.0))
    k = cm.mastery([Interaction(0, 1), Interaction(0, 1), Interaction(1, 0)], 3)
    assert np.allclose(k, [3 / 4, 1 / 3, 1 / 2])
    missing = cfg.model_copy(update={"mastery_model": "akt", "model_dir": tmp_path})
    assert make_mastery_model(missing).name == "count"  # falls back without a trained model


def test_assistments_loader(tmp_path: Path) -> None:
    csv = tmp_path / "skill_builder.csv"
    csv.write_text(
        "order_id,user_id,skill_id,correct,ms_first_response,hint_count,attempt_count\n"
        "3,u1,s2,0,8000,1,2\n1,u1,s1,1,2000,0,1\n2,u1,s1,1,1500,0,1\n"
        "1,u2,s1,0,9000,2,3\n2,u2,,1,100,0,1\n3,u2,s2,1,4000,0,1\n4,u3,s1,1,10,0,1\n",
        encoding="utf-8",
    )
    seqs, skills = load_assistments(csv)
    assert skills == ["s1", "s2"]
    u1 = next(s for s in seqs if len(s) == 3)
    assert [x.concept for x in u1] == [0, 0, 1]  # ordered by order_id
    assert u1[-1].hints == 1 and u1[-1].attempts == 2 and u1[-1].response_seconds == 8.0
    assert len(seqs) == 2  # u3 has a single interaction and is dropped
