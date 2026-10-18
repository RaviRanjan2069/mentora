"""Train and evaluate KT models; AUC is computed on held-out learners."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import roc_auc_score
from torch import nn

from mentora.config.settings import LearnerModelSettings
from mentora.learner_model.kt.data import Sequence_, split_by_learner, to_batch
from mentora.learner_model.kt.models import DKT, AKTStyle, KTKind, build_model


@dataclass(frozen=True)
class KTReport:
    kind: KTKind
    n_concepts: int
    n_train_learners: int
    n_test_learners: int
    test_auc: float
    test_accuracy: float
    epochs: int
    seed: int


def _targets(seqs: list[Sequence_]) -> tuple[torch.Tensor, torch.Tensor]:
    b = to_batch(seqs)
    return b.correct[:, 1:].float(), b.mask[:, 1:]


def _evaluate(model: DKT | AKTStyle, seqs: list[Sequence_], batch_size: int) -> tuple[float, float]:
    model.eval()
    probs, labels = [], []
    with torch.no_grad():
        for i in range(0, len(seqs), batch_size):
            chunk = seqs[i : i + batch_size]
            logits = model.predict_next(to_batch(chunk))
            y, m = _targets(chunk)
            probs.append(torch.sigmoid(logits)[m].numpy())
            labels.append(y[m].numpy())
    p, y_all = np.concatenate(probs), np.concatenate(labels)
    auc = float(roc_auc_score(y_all, p)) if len(set(y_all.tolist())) > 1 else float("nan")
    return auc, float(((p >= 0.5) == (y_all == 1)).mean())


def train_kt(
    kind: KTKind, seqs: list[Sequence_], n_concepts: int, cfg: LearnerModelSettings
) -> tuple[DKT | AKTStyle, KTReport]:
    torch.manual_seed(cfg.kt_seed)
    rng = np.random.default_rng(cfg.kt_seed)
    train, test = split_by_learner(seqs, cfg.kt_test_fraction, cfg.kt_seed)
    model = build_model(kind, n_concepts, cfg.kt_hidden, cfg.kt_heads)
    opt = torch.optim.Adam(model.parameters(), lr=cfg.kt_lr)
    loss_fn = nn.BCEWithLogitsLoss()
    for _epoch in range(cfg.kt_epochs):
        model.train()
        order = rng.permutation(len(train))
        for i in range(0, len(train), cfg.kt_batch_size):
            chunk = [train[j] for j in order[i : i + cfg.kt_batch_size]]
            logits = model.predict_next(to_batch(chunk))
            y, m = _targets(chunk)
            loss = loss_fn(logits[m], y[m])
            opt.zero_grad()
            loss.backward()
            opt.step()
    auc, acc = _evaluate(model, test, cfg.kt_batch_size)
    report = KTReport(kind, n_concepts, len(train), len(test), auc, acc, cfg.kt_epochs, cfg.kt_seed)
    return model, report


def save_model(
    model: DKT | AKTStyle, report: KTReport, directory: Path, hidden: int, heads: int
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"kt_{report.kind}.pt"
    torch.save(
        {"state": model.state_dict(), "report": asdict(report), "hidden": hidden, "heads": heads},
        path,
    )
    (directory / f"kt_{report.kind}.json").write_text(json.dumps(asdict(report), indent=2))
    return path


def load_model(path: Path) -> DKT | AKTStyle:
    blob = torch.load(path, weights_only=False)
    report = blob["report"]
    model = build_model(report["kind"], report["n_concepts"], blob["hidden"], blob["heads"])
    model.load_state_dict(blob["state"])
    model.eval()
    return model
