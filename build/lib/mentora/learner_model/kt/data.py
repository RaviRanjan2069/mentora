"""Interaction sequences for knowledge tracing: synthetic generator and ASSISTments loader."""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from mentora.course import CourseSpec

if TYPE_CHECKING:  # torch is imported only when batching for training (keeps the API light)
    import torch


@dataclass(frozen=True)
class Interaction:
    concept: int  # index into the course concept list
    correct: int  # 0 / 1
    response_seconds: float = 10.0
    hints: int = 0
    attempts: int = 1

    def behaviour(self) -> tuple[float, float, float]:
        """b = (response time, hint use, attempt count), scaled to roughly [0, 1]."""
        return (
            min(math.log1p(max(self.response_seconds, 0.0)) / 5.0, 1.0),
            1.0 if self.hints > 0 else 0.0,
            min(max(self.attempts - 1, 0), 4) / 4.0,
        )


Sequence_ = list[Interaction]


def synthetic_sequences(
    course: CourseSpec, n_learners: int, length: int, seed: int
) -> list[Sequence_]:
    """BKT-style simulated learners (for tests, demos and sanity checks only).

    Each learner has a per-concept latent 'known' state that can flip to known with
    practice (faster when prerequisites are known). Correctness follows slip/guess;
    response time, hint use and attempts depend on the latent state.
    """
    rng = np.random.default_rng(seed)
    keys = [c.key for c in course.concepts]
    idx = {k: i for i, k in enumerate(keys)}
    prereqs = [[idx[p] for p in c.prereqs] for c in course.concepts]
    out: list[Sequence_] = []
    for _ in range(n_learners):
        ability = rng.normal(0.0, 1.0)
        known = rng.random(len(keys)) < 1 / (1 + np.exp(-(ability - 1.2)))
        frontier = 0
        seq: Sequence_ = []
        for _t in range(length):
            # Mostly practise around the frontier of the curriculum, sometimes review.
            if rng.random() < 0.75:
                c = min(frontier + int(rng.integers(0, 3)), len(keys) - 1)
            else:
                c = int(rng.integers(0, frontier + 1))
            prereq_known = all(known[p] for p in prereqs[c]) if prereqs[c] else True
            p_correct = 0.88 if known[c] else (0.25 if prereq_known else 0.12)
            correct = int(rng.random() < p_correct)
            rt = float(rng.lognormal(2.0 if known[c] else 2.8, 0.4))
            hints = int(rng.random() < (0.08 if known[c] else 0.45))
            attempts = 1 + (0 if correct else int(rng.poisson(1.2)))
            seq.append(Interaction(c, correct, rt, hints, attempts))
            p_learn = (0.22 if prereq_known else 0.06) * (1 + 0.3 * ability)
            if not known[c] and rng.random() < max(p_learn, 0.01):
                known[c] = True
            if known[c] and c == frontier:
                frontier = min(frontier + 1, len(keys) - 1)
        out.append(seq)
    return out


def load_assistments(path: Path, max_len: int = 200) -> tuple[list[Sequence_], list[str]]:
    """ASSISTments 2009-2010 skill-builder CSV (columns: user_id, skill_id, correct,
    ms_first_response, hint_count, attempt_count, order_id). See docs/runbook.md."""
    rows: dict[str, list[tuple[int, str, int, float, int, int]]] = defaultdict(list)
    with path.open(encoding="latin-1", newline="") as f:
        for r in csv.DictReader(f):
            if not r.get("skill_id"):
                continue
            rows[r["user_id"]].append(
                (
                    int(r.get("order_id") or 0),
                    r["skill_id"],
                    int(float(r["correct"]) >= 1),
                    max(float(r.get("ms_first_response") or 0), 0) / 1000,
                    int(float(r.get("hint_count") or 0)),
                    int(float(r.get("attempt_count") or 1)),
                )
            )
    skills = sorted({s for seq in rows.values() for _, s, *_ in seq})
    sidx = {s: i for i, s in enumerate(skills)}
    seqs = [
        [Interaction(sidx[s], c, rt, h, a) for _, s, c, rt, h, a in sorted(seq)][:max_len]
        for seq in rows.values()
        if len(seq) >= 2
    ]
    return seqs, skills


@dataclass
class Batch:
    concepts: torch.Tensor  # [B, T] long
    correct: torch.Tensor  # [B, T] long
    behaviour: torch.Tensor  # [B, T, 3] float
    mask: torch.Tensor  # [B, T] bool (real steps)


def to_batch(seqs: list[Sequence_]) -> Batch:
    import torch

    t_max = max(len(s) for s in seqs)
    b = len(seqs)
    concepts = torch.zeros(b, t_max, dtype=torch.long)
    correct = torch.zeros(b, t_max, dtype=torch.long)
    behaviour = torch.zeros(b, t_max, 3)
    mask = torch.zeros(b, t_max, dtype=torch.bool)
    for i, seq in enumerate(seqs):
        for t, x in enumerate(seq):
            concepts[i, t] = x.concept
            correct[i, t] = x.correct
            behaviour[i, t] = torch.tensor(x.behaviour())
            mask[i, t] = True
    return Batch(concepts, correct, behaviour, mask)


def split_by_learner(
    seqs: list[Sequence_], test_fraction: float, seed: int
) -> tuple[list[Sequence_], list[Sequence_]]:
    order = np.random.default_rng(seed).permutation(len(seqs))
    n_test = max(1, int(len(seqs) * test_fraction))
    test = [seqs[i] for i in order[:n_test]]
    train = [seqs[i] for i in order[n_test:]]
    return train, test
