"""Build (s, a, mu, r, s') episodes from the logs for offline RL and OPE.

Each step joins a ``transitions`` row with the tutor-action statement logged in the same
turn, which carries the feasible set F(s) and the full behaviour distribution. Only
closed steps (reward known) are used. Splits are always by learner, never by step.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mentora.db import models as m
from mentora.logging_xapi.statements import VERBS, Statement
from mentora.policy.catalogue import Catalogue


@dataclass
class Step:
    session_id: str
    learner_id: str
    t: int
    state: np.ndarray
    action: int  # index into Dataset.action_ids
    propensity: float
    reward: float
    next_state: np.ndarray
    feasible: np.ndarray  # bool mask over actions: F(s_t)
    behaviour_probs: np.ndarray  # mu(.|s_t) over actions (zeros outside F)
    graded: bool  # the integrity constraint was active
    terminal: bool = False
    next_feasible: np.ndarray | None = None  # F(s_{t+1}); None when terminal


@dataclass
class Episode:
    session_id: str
    learner_id: str
    steps: list[Step]


@dataclass
class Dataset:
    action_ids: list[str]
    episodes: list[Episode]
    groups: dict[str, dict[str, str]] = field(default_factory=dict)  # learner -> attributes

    @property
    def n_actions(self) -> int:
        return len(self.action_ids)

    @property
    def state_dim(self) -> int:
        return int(self.episodes[0].steps[0].state.shape[0]) if self.episodes else 0

    @property
    def steps(self) -> list[Step]:
        return [s for e in self.episodes for s in e.steps]

    @property
    def learners(self) -> list[str]:
        return sorted({e.learner_id for e in self.episodes})

    def subset(self, learners: set[str]) -> Dataset:
        return Dataset(
            self.action_ids, [e for e in self.episodes if e.learner_id in learners], self.groups
        )

    def arrays(self) -> dict[str, np.ndarray]:
        steps = self.steps
        a = len(self.action_ids)
        return {
            "s": np.stack([s.state for s in steps]),
            "a": np.asarray([s.action for s in steps]),
            "r": np.asarray([s.reward for s in steps], dtype=float),
            "s2": np.stack([s.next_state for s in steps]),
            "done": np.asarray([s.terminal for s in steps], dtype=float),
            "f": np.stack([s.feasible for s in steps]),
            "f2": np.stack(
                [
                    s.next_feasible if s.next_feasible is not None else np.ones(a, bool)
                    for s in steps
                ]
            ),
            "mu": np.asarray([s.propensity for s in steps], dtype=float),
        }


def build_dataset(session_factory: sessionmaker[Session], catalogue: Catalogue) -> Dataset:
    action_ids = [a.id for a in catalogue]
    index = {aid: i for i, aid in enumerate(action_ids)}
    n = len(action_ids)
    with session_factory() as db:
        rows = db.scalars(
            select(m.Transition)
            .where(m.Transition.reward.is_not(None), m.Transition.next_state.is_not(None))
            .order_by(m.Transition.session_id, m.Transition.t)
        ).all()
        stmts = db.execute(
            select(m.Event.session_id, m.Event.turn, m.Event.statement).where(
                m.Event.verb == VERBS["received"]
            )
        ).all()
        learners = db.scalars(select(m.Learner)).all()
    tutor = {}
    for sid, turn, raw in stmts:
        ext = Statement.model_validate(raw).tutor_action
        if ext is not None:
            tutor[(sid, turn)] = ext

    by_session: dict[str, list[Step]] = defaultdict(list)
    for r in rows:
        ext = tutor.get((r.session_id, r.t))
        if ext is None or r.action_id not in index:
            continue
        feasible = np.zeros(n, bool)
        for aid in ext.filter_outcome.feasible_action_ids:
            if aid in index:
                feasible[index[aid]] = True
        probs = np.zeros(n)
        for aid, p in (ext.action_probs or {r.action_id: 1.0}).items():
            if aid in index:
                probs[index[aid]] = p
        by_session[r.session_id].append(
            Step(
                session_id=r.session_id,
                learner_id=r.learner_id,
                t=r.t,
                state=np.asarray(r.state, dtype=float),
                action=index[r.action_id],
                propensity=float(r.propensity),
                reward=float(r.reward or 0.0),
                next_state=np.asarray(r.next_state, dtype=float),
                feasible=feasible,
                behaviour_probs=probs,
                graded="integrity" in ext.filter_outcome.removed,
            )
        )
    episodes = []
    for sid, steps in by_session.items():
        steps.sort(key=lambda s: s.t)
        for cur, nxt in itertools.pairwise(steps):
            cur.next_feasible = nxt.feasible
        steps[-1].terminal = True
        episodes.append(Episode(sid, steps[0].learner_id, steps))
    episodes.sort(key=lambda e: e.session_id)
    groups = {
        lr.id: {
            "gender": lr.gender or "unknown",
            "prior_tercile": str(lr.prior_achievement_tercile)
            if lr.prior_achievement_tercile
            else "unknown",
        }
        for lr in learners
    }
    return Dataset(action_ids, episodes, groups)


def split_by_learner(data: Dataset, val_fraction: float, seed: int) -> tuple[Dataset, Dataset]:
    learners = data.learners
    order = np.random.default_rng(seed).permutation(len(learners))
    n_val = max(1, round(len(learners) * val_fraction))
    val = {learners[i] for i in order[:n_val]}
    return data.subset(set(learners) - val), data.subset(val)
