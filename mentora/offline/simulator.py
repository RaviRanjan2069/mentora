"""Learner simulator - FOR DEBUGGING AND SANITY CHECKS ONLY. Simulated results are never
evidence about real learners; every report labels them "simulation".

Simulated learners talk to the real orchestrator (real safety filter, policy, logging and
reward), so the simulator can (a) generate synthetic logs with propensities for testing
the offline pipeline and (b) check that a candidate policy never leaves F(s).

* latent mastery: per-concept known/unknown that flips with practice (BKT-style); content
  help (hints, examples, explanations) raises the learning rate
* behaviour: per-action response probabilities (set a goal when asked, reflect when asked,
  ignore a prompt), which can be refitted from real logs by logistic regression
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from mentora.config.settings import Settings
from mentora.course import CourseSpec, load_course, load_items, upsert_course, upsert_items
from mentora.db import ASC, StoreFactory
from mentora.db import models as m
from mentora.llm.backends.offline import OfflineLLM
from mentora.llm.client import LLMClient
from mentora.logging_xapi.lrs_client import SqlLRSClient
from mentora.logging_xapi.statements import VERBS
from mentora.orchestrator.turn import Orchestrator
from mentora.policy.base import Proposer
from mentora.rag import build_pipeline
from mentora.rag.embeddings import HashingEmbedder
from mentora.rag.ingest import build_passages, embed_passages, load_documents, store_passages

LABEL = "simulation (debugging only - not evidence about real learners)"
ROOT = Path(__file__).resolve().parents[2]
HELP_MOVES = {"graded_hint", "worked_example", "concept_explanation"}


@dataclass
class ResponseModel:
    """P(learner does X | last tutor move). Defaults; refit with fit_response_models()."""

    p_goal_when_asked: float = 0.75
    p_goal_unprompted: float = 0.05
    p_reflect_when_asked: float = 0.6
    p_reflect_unprompted: float = 0.03
    p_ignore: float = 0.1
    p_hint_request_after_wrong: float = 0.3
    p_distress: float = 0.005


@dataclass
class SimStats:
    label: str
    sessions: int = 0
    turns: int = 0
    violations: int = 0
    escalations: int = 0
    actions: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "sessions": self.sessions,
            "turns": self.turns,
            "violations": self.violations,
            "escalations": self.escalations,
            "top_actions": dict(self.actions.most_common(8)),
        }


def simulation_settings(settings: Settings, policy_mode: str) -> Settings:
    """Fast, offline components: hashing embedder, lexical reranker/judge, template LLM."""
    return settings.model_copy(
        update={
            "llm": settings.llm.model_copy(update={"backend": "offline"}),
            "rag": settings.rag.model_copy(
                update={"embedder": "hashing", "reranker": "lexical", "grounding_judge": "lexical"}
            ),
            "policy": settings.policy.model_copy(update={"mode": policy_mode}),
            "app": settings.app.model_copy(update={"mode": "adaptive"}),
        }
    )


def seed_course(factory: StoreFactory, course: CourseSpec) -> int:
    with factory.begin() as db:
        course_id = upsert_course(db, course).id
        upsert_items(db, course_id, load_items(ROOT / "data" / "sample" / "items.yaml"))
    drafts = build_passages(load_documents(ROOT / "data" / "sample" / "corpus"), course, 300, 40)
    store_passages(factory, course_id, embed_passages(drafts, HashingEmbedder(384)))
    return course_id


def count_violations(factory: StoreFactory) -> int:
    """Independent re-check of the logs: chosen action inside the logged F(s), and no
    Directive / worked example where the integrity constraint was active."""
    bad = 0
    for st in SqlLRSClient(factory).query(verb=VERBS["received"]):
        ext = st.tutor_action
        if ext is None:
            continue
        outside = ext.action.id not in ext.filter_outcome.feasible_action_ids
        integrity_breach = "integrity" in ext.filter_outcome.removed and (
            ext.action.style == "Directive" or ext.action.move == "worked_example"
        )
        bad += int(outside or integrity_breach)
    return bad


def run_simulation(
    settings: Settings,
    factory: StoreFactory,
    *,
    n_sessions: int,
    turns: int,
    seed: int,
    proposer: Proposer | None = None,
    policy_mode: str = "collect",
    responses: ResponseModel | None = None,
    on_session: Callable[[int], None] | None = None,
    reward_terms: list[Any] | None = None,
) -> SimStats:
    rng = random.Random(seed)
    nrng = np.random.default_rng(seed)
    resp = responses or ResponseModel()
    sim = simulation_settings(settings, policy_mode)
    course = load_course(sim.app.concepts_file)
    course_id = seed_course(factory, course)
    clock_now = [datetime(2026, 9, 8, 9, tzinfo=UTC)]

    def clock() -> datetime:
        clock_now[0] += timedelta(seconds=30)
        return clock_now[0]

    orch = Orchestrator(
        sim,
        factory,
        client=LLMClient(OfflineLLM()),
        course=course,
        rag=build_pipeline(sim, factory, course_id),
        proposer=proposer,
        clock=clock,
    )
    orch.reward_terms = reward_terms
    with factory() as db:
        items = db.find(m.Item, {"course_id": course_id}, sort=[("id", ASC)])
        keys = dict(db.values(m.Concept, ["id", "key"], {"course_id": course_id}))
        item_concepts = {i.id: [keys[c] for c in sorted(i.concept_ids) if c in keys] for i in items}

    n_learners = max(4, n_sessions // 3)
    learners = []
    with factory.begin() as db:
        for i in range(n_learners):
            lid = f"lrn_sim_{seed}_{i:03d}"
            learners.append(lid)
            if db.get(m.Learner, lid) is None:
                db.add(
                    m.Learner(
                        id=lid,
                        gender=rng.choice(["female", "male"]),
                        prior_achievement_tercile=rng.randint(1, 3),
                    )
                )
    ability = {lid: float(nrng.normal()) for lid in learners}
    known: dict[str, set[str]] = {lid: set() for lid in learners}
    stats = SimStats(LABEL)

    for s in range(n_sessions):
        lid = learners[s % n_learners]
        clock_now[0] += timedelta(days=1)
        r = orch.start_session(lid)
        sid, last = r.session_id, r.action_id
        stats.actions[last] += 1
        quiz = rng.sample(items, k=min(3, len(items)))
        session_items = list(quiz)
        orch.start_quiz(sid, [i.id for i in quiz])
        current, attempts, goal_set = None, 0, False
        for _ in range(turns):
            move = last.split(".")[1] if "." in last else last
            if rng.random() < resp.p_distress:
                r = orch.handle_message(sid, "I can't cope with this anymore")
            elif (
                move in ("elicit_smart_goal", "recall_past_goals")
                and not goal_set
                and (rng.random() < resp.p_goal_when_asked)
            ):
                topic = item_concepts[session_items[0].id][0].replace("_", " ")
                r = orch.handle_message(sid, f"My goal is to finish 3 {topic} exercises today")
                goal_set = True
            elif (
                move
                in (
                    "socratic_reflection",
                    "attribution_question",
                    "record_lesson",
                    "compare_outcome_goal",
                )
                and rng.random() < resp.p_reflect_when_asked
            ):
                r = orch.handle_message(
                    sid, "I got it because I practised. Next time I'll trace it first."
                )
            elif "." in last and rng.random() < resp.p_ignore:
                r = orch.handle_message(sid, "ok")
            elif current is None:
                if not quiz:
                    break
                current, attempts = quiz.pop(0), 0
                r = orch.present_item(sid, current.id)
            elif attempts > 0 and rng.random() < resp.p_hint_request_after_wrong:
                r = orch.handle_message(sid, "can I get a hint?")
            else:
                concepts = item_concepts[current.id]
                k = all(c in known[lid] for c in concepts)
                boost = 0.15 if move in HELP_MOVES else 0.0
                p_right = (0.88 if k else 0.2 + 0.05 * ability[lid]) + boost
                correct = rng.random() < min(max(p_right, 0.02), 0.98)
                conf = min(max((0.75 if k else 0.45) + rng.gauss(0, 0.15), 0.0), 1.0)
                response = current.answer_key if correct else "wrong"
                r = orch.handle_answer(
                    sid,
                    current.id,
                    response or "x",
                    confidence=round(conf, 2),
                    response_seconds=rng.uniform(5, 60),
                )
                attempts += 1
                if not k:
                    p_learn = (
                        0.12
                        + 0.03 * ability[lid]
                        + (0.18 if move in HELP_MOVES else 0.0)
                        + (0.05 if goal_set else 0.0)
                    )
                    if rng.random() < max(p_learn, 0.01):
                        known[lid].update(concepts)
                if correct or attempts >= 3:
                    current = None
            last = r.action_id
            stats.actions[last] += 1
            stats.turns += 1
            stats.escalations += int(r.escalated)
        orch.end_session(sid)
        stats.sessions += 1
        if on_session:
            on_session(s)
    stats.violations = count_violations(factory)
    return stats


def fit_response_models(factory: StoreFactory) -> tuple[ResponseModel, dict[str, float]]:
    """Refit P(goal | asked) and P(reflect | asked) from real logs with logistic regression on
    the previous tutor move; returns the model and the observed rates (for a calibration
    table comparing simulated with real behaviour)."""
    from sklearn.linear_model import LogisticRegression

    from mentora.learner_model.srl_tagger import trace_tags

    rows: list[tuple[str, str]] = []
    for sid in {st.session_id for st in SqlLRSClient(factory).query() if st.session_id}:
        last = "none"
        for st in SqlLRSClient(factory).query(session_id=sid):
            ext = st.tutor_action
            if ext is not None:
                last = ext.action.move
            elif st.verb.id == VERBS["commented"] and st.result and st.result.response:
                tags = trace_tags(st.result.response)
                kind = (
                    "goal"
                    if tags.goal_stated
                    else "reflect"
                    if (tags.attribution or tags.self_evaluation)
                    else "other"
                )
                rows.append((last, kind))
    model, rates = ResponseModel(), dict[str, float]()
    if len(rows) < 30:
        return model, rates
    asked_goal = [k == "goal" for last, k in rows if last == "elicit_smart_goal"]
    asked_refl = [k == "reflect" for last, k in rows if last == "socratic_reflection"]
    x = np.asarray(
        [
            [
                1.0 if last == "elicit_smart_goal" else 0.0,
                1.0 if last == "socratic_reflection" else 0.0,
            ]
            for last, _ in rows
        ]
    )
    for target, attr_asked, attr_un, col in (
        ("goal", "p_goal_when_asked", "p_goal_unprompted", 0),
        ("reflect", "p_reflect_when_asked", "p_reflect_unprompted", 1),
    ):
        y = np.asarray([k == target for _, k in rows])
        if y.any() and not y.all():
            lr = LogisticRegression().fit(x, y)
            probe = np.zeros((2, 2))
            probe[0, col] = 1.0
            p = lr.predict_proba(probe)[:, 1]
            setattr(model, attr_asked, float(p[0]))
            setattr(model, attr_un, float(p[1]))
    rates["observed_goal_when_asked"] = float(np.mean(asked_goal)) if asked_goal else float("nan")
    rates["observed_reflect_when_asked"] = (
        float(np.mean(asked_refl)) if asked_refl else float("nan")
    )
    return model, rates
