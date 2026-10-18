"""One tutoring turn (design Section 1):

event -> log xAPI -> update learner model -> state s_t + memory recall
-> safety filter F(s_t) -> policy picks a_t (or WAIT / ESCALATE) with propensity
-> agent phrases a_t (RAG-grounded) -> grounding + integrity checks -> reply + "why"
-> reward for the previous step; store (s, a, mu, r, s')
"""

from __future__ import annotations

import hashlib
import random
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from mentora.agents import AgentReply, TurnContext, TutorTeam
from mentora.config.settings import Settings
from mentora.course import CourseSpec, item_concept_keys, upsert_course
from mentora.db import models as m
from mentora.learner_model.engagement import engagement
from mentora.learner_model.hmm_tactics import TacticHMM
from mentora.learner_model.kt.data import Interaction
from mentora.learner_model.kt.mastery import MasteryModel, make_mastery_model
from mentora.learner_model.requests import Request, classify_request
from mentora.learner_model.srl_tagger import SRLTagger, SRLTags
from mentora.learner_model.state import LearnerSnapshot, feature_names
from mentora.learner_model.tracker import LearnerTracker
from mentora.llm.client import LLMClient
from mentora.llm.prompts import RenderedPrompt, default_registry
from mentora.llm.types import Message
from mentora.logging_xapi.lrs_client import SqlLRSClient
from mentora.logging_xapi.statements import (
    VERBS,
    XAPI_BASE,
    Statement,
    TutorActionExtension,
    learner_message,
    lms_event,
    quiz_answer,
    tutor_action,
)
from mentora.memory.service import MemoryService, NullMemory
from mentora.policy.base import Decision, PolicyObs, Proposer
from mentora.policy.catalogue import ESCALATE, WAIT, Catalogue, default_catalogue
from mentora.policy.collect import BehaviourPolicy
from mentora.policy.registry import active_policy
from mentora.policy.rule_policy import RulePolicy
from mentora.rag.grounding import HeuristicClaimDetector, check_grounding, make_judge
from mentora.rag.ingest import tag_concepts
from mentora.rag.rerank import RagPipeline
from mentora.rag.retrieve import Passage
from mentora.rag.text import CITATION_RE, content_words, split_sentences
from mentora.reward.reward import (
    ANSWER_GIVING_MOVES,
    RewardTerms,
    StepOutcome,
    compute_reward,
)
from mentora.safety.feasibility import (
    FilterContext,
    FilterResult,
    feasible_set,
    unsolicited_in_window,
)
from mentora.safety.integrity_check import ItemView, integrity_check
from mentora.safety.teacher_rules import load_teacher_rules
from mentora.safety.wellbeing import detect_distress

Clock = Callable[[], datetime]


class TurnError(Exception):
    pass


@dataclass(frozen=True)
class TurnResult:
    session_id: str
    turn: int
    action_id: str
    reply: str | None
    why: str | None
    policy_reason: str
    propensity: float
    escalated: bool = False
    show_support_resources: bool = False
    passage_ids: list[str] = field(default_factory=list)
    correct: bool | None = None
    # Context for the learner UI (never used by the policy).
    phase: str = ""
    topic: str | None = None
    sources: list[dict[str, object]] = field(default_factory=list)
    # "course" | "general" | "unverified" | None (see AgentReply.answer_source)
    answer_source: str | None = None


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    transitions: int
    session_return: float


@dataclass
class _StepFlags:
    goal_set: bool = False
    g_smart: float | None = None
    q_refl: float | None = None
    learner_initiated: bool = False
    goal_attained: bool = False


@dataclass
class _Pending:
    t: int
    action_id: str
    state: list[float]
    gave_help_before_attempt: bool


@dataclass
class _ItemInfo:
    id: int
    text: str
    graded: bool
    answer_key: str | None
    item_type: str
    concepts: list[str]


@dataclass
class _Runtime:
    session_id: str
    learner_id: str
    tracker: LearnerTracker
    t: int = 0
    pending: _Pending | None = None
    flags: _StepFlags = field(default_factory=_StepFlags)
    recent_unsolicited: list[datetime] = field(default_factory=list)
    event_times: list[datetime] = field(default_factory=list)
    items_presented: int = 0
    item_just_presented: bool = False
    current_item: _ItemInfo | None = None
    quiz_remaining: set[int] = field(default_factory=set)
    quiz_attempts: dict[int, int] = field(default_factory=dict)
    quiz_completed: bool = False
    last_tutor_text: str | None = None
    last_passages: list[Passage] = field(default_factory=list)


def _answer_matches(response: str, item: _ItemInfo) -> bool:
    key = (item.answer_key or "").strip().lower()
    got = response.strip().lower().strip("()").strip()
    if item.item_type == "mcq":
        return got[:1] == key[:1] if got else False
    return " ".join(got.split()) == " ".join(key.split())


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        *,
        client: LLMClient,
        course: CourseSpec,
        rag: RagPipeline | None = None,
        memory: MemoryService | None = None,
        mastery_model: MasteryModel | None = None,
        hmm: TacticHMM | None = None,
        proposer: Proposer | None = None,
        catalogue: Catalogue | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.settings = settings
        self.factory = session_factory
        self.client = client
        self.course = course
        self.catalogue = catalogue or default_catalogue()
        self.rag = rag
        self.static = settings.app.mode == "static"
        self.memory: MemoryService = NullMemory() if self.static or memory is None else memory
        self.mastery_model = mastery_model or make_mastery_model(settings.learner_model)
        self.hmm = hmm or TacticHMM.load_or_uninformed(
            settings.learner_model.model_dir / "tactic_hmm.json"
        )
        self.clock: Clock = clock or (lambda: datetime.now(UTC))
        self.lrs = SqlLRSClient(session_factory)
        self.judge = make_judge(settings, client)
        self.team = TutorTeam(client, catalogue=self.catalogue, settings=settings, judge=self.judge)
        self.tagger = SRLTagger.from_settings(settings, client)
        self.features = feature_names(settings.learner_model)
        with session_factory.begin() as db:
            self.course_id = upsert_course(db, course).id
            policy_row = active_policy(db)
        if proposer is None:
            if policy_row.type in ("cql_ensemble", "tabular") and not self.static:
                from mentora.offline.policies import load_proposer

                proposer = load_proposer(
                    policy_row.type, policy_row.config, self.catalogue, policy_row.version
                )
            else:  # the rule policy; the static control condition always uses it
                proposer = RulePolicy(self.catalogue, version="rule-v1")
        mode = "deploy" if self.static else settings.policy.mode
        self.policy = BehaviourPolicy(
            proposer,
            mode=mode,
            temperature=settings.policy.collect_temperature,
            novelty_beta=settings.policy.novelty_beta,
            explore_on_requests=settings.policy.explore_on_requests,
        )
        self._runtimes: dict[str, _Runtime] = {}
        # Optional sink for per-step reward terms (lambda-sensitivity analysis).
        self.reward_terms: list[tuple[str, int, RewardTerms]] | None = None

    # --- public API ------------------------------------------------------------------------

    def refresh_rag(self) -> None:
        """Rebuild the retrieval index after course material changed."""
        from mentora.rag import build_pipeline

        with self.factory() as db:
            has = db.scalars(
                select(m.CorpusPassage.id).where(m.CorpusPassage.course_id == self.course_id)
            ).first()
        self.rag = build_pipeline(self.settings, self.factory, self.course_id) if has else None

    def start_session(self, learner_id: str) -> TurnResult:
        now = self.clock()
        with self.factory.begin() as db:
            if db.get(m.Learner, learner_id) is None:
                db.add(m.Learner(id=learner_id))
            sess = m.Session(
                learner_id=learner_id,
                course_id=self.course_id,
                mode="static" if self.static else "adaptive",
                policy_version=self.policy.version,
                started_at=now,
            )
            db.add(sess)
            db.flush()
            session_id = sess.id
        rt = self._new_runtime(session_id, learner_id)
        self._runtimes[session_id] = rt
        st = lms_event(
            learner_id,
            session_id,
            rt.t,
            "initialized",
            f"{XAPI_BASE}/sessions/{session_id}",
            "Tutoring session",
            now,
        )
        self._log_and_observe(rt, st)
        return self._turn(rt, learner_text=None, request="none", tags=None)

    def handle_message(self, session_id: str, text: str) -> TurnResult:
        rt = self._runtime(session_id)
        text = text.strip()
        if not text:
            raise TurnError("empty message")
        tags = self.tagger.tag(text, rt.last_tutor_text)
        request = classify_request(text)
        st = learner_message(
            rt.learner_id, session_id, rt.t, text, self.clock(), srl_tags=tags.model_dump()
        )
        self._log_and_observe(rt, st, tags, request)
        self._update_goals(rt, text, tags)
        return self._turn(rt, learner_text=text, request=request, tags=tags)

    def present_item(self, session_id: str, item_id: int) -> TurnResult:
        rt = self._runtime(session_id)
        rt.current_item = self._item(item_id)
        rt.items_presented += 1
        rt.item_just_presented = True
        rt.tracker.start_item(item_id)
        st = lms_event(
            rt.learner_id,
            session_id,
            rt.t,
            "launched",
            f"{XAPI_BASE}/items/{item_id}",
            "Item presented",
            self.clock(),
        )
        self._log_and_observe(rt, st)
        result = self._turn(rt, learner_text=None, request="none", tags=None)
        rt.item_just_presented = False
        return result

    def start_quiz(self, session_id: str, item_ids: Sequence[int]) -> None:
        rt = self._runtime(session_id)
        rt.quiz_remaining = set(item_ids)
        rt.quiz_attempts = {}
        rt.quiz_completed = False

    def handle_answer(
        self,
        session_id: str,
        item_id: int,
        response: str,
        *,
        confidence: float | None = None,
        response_seconds: float | None = None,
        hints_used: int = 0,
    ) -> TurnResult:
        rt = self._runtime(session_id)
        item = (
            rt.current_item
            if rt.current_item and rt.current_item.id == item_id
            else self._item(item_id)
        )
        correct = _answer_matches(response, item)
        attempt = rt.quiz_attempts.get(item_id, 0) + 1
        rt.quiz_attempts[item_id] = attempt
        st = quiz_answer(
            rt.learner_id,
            session_id,
            rt.t,
            item_id,
            response,
            correct,
            confidence=confidence,
            timestamp=self.clock(),
            response_seconds=response_seconds,
            hints_used=hints_used,
            attempt=attempt,
        )
        self._log_and_observe(rt, st)
        if item_id in rt.quiz_remaining and (
            correct or attempt >= self.settings.goals.quiz_max_attempts
        ):
            rt.quiz_remaining.discard(item_id)
            rt.quiz_completed = not rt.quiz_remaining
        self._check_goal_attained(rt)
        result = self._turn(rt, learner_text=None, request="none", tags=None)
        rt.quiz_completed = False
        return TurnResult(**{**result.__dict__, "correct": correct})

    def end_session(self, session_id: str) -> SessionSummary:
        rt = self._runtime(session_id)
        now = self.clock()
        st = lms_event(
            rt.learner_id,
            session_id,
            rt.t,
            "terminated",
            f"{XAPI_BASE}/sessions/{session_id}",
            "Tutoring session",
            now,
        )
        self._log_and_observe(rt, st)
        state, _snap = self._state(rt)
        self._close_pending(rt, state)
        with self.factory.begin() as db:
            sess = db.get(m.Session, session_id)
            assert sess is not None
            sess.ended_at = now
            rows = db.scalars(
                select(m.Transition).where(m.Transition.session_id == session_id)
            ).all()
            ret = sum(r.reward or 0.0 for r in rows)
            n = len(rows)
        self.memory.end_session(session_id)
        self._runtimes.pop(session_id, None)
        return SessionSummary(session_id, n, ret)

    # --- runtime ---------------------------------------------------------------------------

    def _new_runtime(self, session_id: str, learner_id: str) -> _Runtime:
        with self.factory() as db:
            item_concepts = item_concept_keys(db, self.course_id)
            prior = self.learner_history(db, learner_id, session_id, item_concepts)
        tracker = LearnerTracker(
            self.course,
            self.settings.learner_model,
            self.mastery_model,
            self.hmm,
            item_concepts,
            prior,
        )
        return _Runtime(session_id, learner_id, tracker)

    def learner_history(
        self, db: Session, learner_id: str, session_id: str, item_concepts: dict[int, list[str]]
    ) -> list[Interaction]:
        """All answers from earlier sessions, so mastery carries over between sessions."""
        rows = db.scalars(
            select(m.Event.statement)
            .where(
                m.Event.learner_id == learner_id,
                m.Event.session_id != session_id,
                m.Event.verb == "http://adlnet.gov/expapi/verbs/answered",
            )
            .order_by(m.Event.timestamp)
        ).all()
        index = {c.key: i for i, c in enumerate(self.course.concepts)}
        out = []
        for raw in rows:
            st = Statement.model_validate(raw)
            keys = item_concepts.get(st.item_id or -1, [])
            concept = next((index[k] for k in keys if k in index), None)
            if concept is not None and st.result is not None:
                out.append(Interaction(concept, int(bool(st.result.success))))
        return out

    def _runtime(self, session_id: str) -> _Runtime:
        rt = self._runtimes.get(session_id)
        if rt is not None:
            return rt
        with self.factory() as db:
            sess = db.get(m.Session, session_id)
            if sess is None or sess.ended_at is not None:
                raise TurnError(f"no open session {session_id}")
            learner_id = sess.learner_id
            pending = db.scalars(
                select(m.Transition)
                .where(m.Transition.session_id == session_id)
                .order_by(m.Transition.t.desc())
            ).first()
        rt = self._new_runtime(session_id, learner_id)
        for st in self.lrs.query(session_id=session_id):  # rebuild by replaying the log
            ext = st.tutor_action
            if ext is not None and self.catalogue.is_unsolicited(ext.action):
                rt.recent_unsolicited.append(st.timestamp)
            if st.verb.id.endswith("/launched") and st.item_id is not None:
                rt.current_item = self._item(st.item_id)
                rt.tracker.start_item(st.item_id)
            rt.tracker.observe(
                st,
                request=classify_request(st.result.response)
                if st.verb.id.endswith("/commented") and st.result
                else None,
            )
            rt.event_times.append(st.timestamp)
        if pending is not None:
            rt.t = pending.t + 1
            if pending.reward is None:
                rt.pending = _Pending(pending.t, pending.action_id, list(pending.state), False)
        self._runtimes[session_id] = rt
        return rt

    def _item(self, item_id: int) -> _ItemInfo:
        with self.factory() as db:
            item = db.get(m.Item, item_id)
            if item is None or item.course_id != self.course_id:
                raise TurnError(f"unknown item {item_id}")
            keys = item_concept_keys(db, self.course_id).get(item_id, [])
            return _ItemInfo(item.id, item.text, item.graded, item.answer_key, item.item_type, keys)

    def _log_and_observe(
        self,
        rt: _Runtime,
        st: Statement,
        tags: SRLTags | None = None,
        request: Request | None = None,
    ) -> None:
        self.lrs.store(st)
        rt.tracker.observe(st, tags, request)
        rt.event_times.append(st.timestamp)

    # --- goals -----------------------------------------------------------------------------

    def _active_goal(self, db: Session, rt: _Runtime) -> m.Goal | None:
        return db.scalars(
            select(m.Goal)
            .where(
                m.Goal.learner_id == rt.learner_id,
                m.Goal.course_id == self.course_id,
                m.Goal.status == "active",
            )
            .order_by(m.Goal.id.desc())
        ).first()

    def _update_goals(self, rt: _Runtime, text: str, tags: SRLTags) -> None:
        srl = tags.model_dump()
        srl.pop("help_request")
        rt.flags.learner_initiated = rt.flags.learner_initiated or any(srl.values())
        if tags.self_evaluation or tags.attribution or tags.adaptation_intent:
            rt.flags.q_refl = self.tagger.reflection_quality(text)
        with self.factory.begin() as db:
            if tags.goal_stated:
                concepts = list(tag_concepts(text, self.course.concepts))
                if not concepts and rt.current_item is not None:
                    concepts = rt.current_item.concepts
                for old in db.scalars(
                    select(m.Goal).where(
                        m.Goal.learner_id == rt.learner_id,
                        m.Goal.status == "active",
                        m.Goal.course_id == self.course_id,
                    )
                ):
                    old.status = "abandoned"
                g_smart = self.tagger.goal_smart(text)
                goal = m.Goal(
                    learner_id=rt.learner_id,
                    course_id=self.course_id,
                    session_id=rt.session_id,
                    text=text,
                    concept_keys=concepts,
                    smart_score=g_smart,
                )
                db.add(goal)
                db.flush()
                db.add(
                    m.Plan(goal_id=goal.id, steps=[{"concept": c, "done": False} for c in concepts])
                )
                rt.flags.goal_set, rt.flags.g_smart = True, g_smart
            if tags.plan_stated:
                goal_row = self._active_goal(db, rt)
                if goal_row is not None:
                    plan = db.scalars(select(m.Plan).where(m.Plan.goal_id == goal_row.id)).first()
                    if plan is not None:
                        plan.steps = [*plan.steps, {"text": text, "done": False}]

    def _check_goal_attained(self, rt: _Runtime) -> None:
        threshold = self.settings.goals.attain_mastery
        with self.factory.begin() as db:
            goal = self._active_goal(db, rt)
            if goal is None or not goal.concept_keys:
                return
            k = rt.tracker.concept_mastery(goal.concept_keys)
            plan = db.scalars(select(m.Plan).where(m.Plan.goal_id == goal.id)).first()
            if plan is not None:
                steps = []
                for s in plan.steps:
                    if "concept" in s:
                        km = rt.tracker.concept_mastery([s["concept"]])
                        s = {**s, "done": km is not None and km >= threshold}
                    steps.append(s)
                plan.steps = steps
                concept_steps = [s for s in steps if "concept" in s]
                plan.progress = (
                    sum(s["done"] for s in concept_steps) / len(concept_steps)
                    if concept_steps
                    else 0.0
                )
            if k is not None and k >= threshold:
                goal.status = "attained"
                goal.attained_at = self.clock()
                rt.flags.goal_attained = True

    # --- state -----------------------------------------------------------------------------

    def _state(self, rt: _Runtime) -> tuple[list[float], LearnerSnapshot]:
        now = self.clock()
        cfg = self.settings.learner_model
        window_start = now - timedelta(days=cfg.engagement_window_days)
        with self.factory() as db:
            goal = self._active_goal(db, rt)
            plan = (
                db.scalars(select(m.Plan).where(m.Plan.goal_id == goal.id)).first()
                if goal
                else None
            )
            starts = db.scalars(
                select(m.Session.started_at).where(
                    m.Session.learner_id == rt.learner_id, m.Session.started_at >= window_start
                )
            ).all()
            times = db.scalars(
                select(m.Event.timestamp).where(
                    m.Event.learner_id == rt.learner_id, m.Event.timestamp >= window_start
                )
            ).all()
        eng = engagement(starts, times, rt.event_times, now, cfg)
        snap = rt.tracker.snapshot(
            goal_concepts=goal.concept_keys if goal else [],
            has_active_goal=goal is not None,
            plan_progress=plan.progress if plan else 0.0,
            engagement=eng,
        )
        return rt.tracker.state_vector(snap), snap

    def _feature(self, state: list[float], name: str) -> float:
        return state[self.features.index(name)]

    def _close_pending(self, rt: _Runtime, state: list[float]) -> None:
        """Reward for the previous decision, now that its outcome is known."""
        p = rt.pending
        if p is None:
            return
        outcome = StepOutcome(
            goal_mastery_before=self._feature(p.state, "goal_mastery"),
            goal_mastery_after=self._feature(state, "goal_mastery"),
            calibration_before=self._feature(p.state, "calibration_error"),
            calibration_after=self._feature(state, "calibration_error"),
            goal_set=rt.flags.goal_set,
            g_smart=rt.flags.g_smart,
            q_refl=rt.flags.q_refl,
            learner_initiated_srl=rt.flags.learner_initiated,
            goal_attained=rt.flags.goal_attained,
            gave_help_before_attempt=p.gave_help_before_attempt,
            unsolicited_over_limit=max(
                0,
                unsolicited_in_window(
                    FilterContext(now=self.clock(), recent_unsolicited=rt.recent_unsolicited),
                    self.settings.safety.window_minutes,
                )
                - self.settings.safety.n_max,
            ),
        )
        terms = compute_reward(self.catalogue.get(p.action_id), outcome, self.settings.reward)
        if self.reward_terms is not None:
            self.reward_terms.append((rt.session_id, p.t, terms))
        with self.factory.begin() as db:
            db.execute(
                update(m.Transition)
                .where(m.Transition.session_id == rt.session_id, m.Transition.t == p.t)
                .values(reward=terms.total, next_state=state)
            )
        rt.pending = None
        rt.flags = _StepFlags()

    # --- the turn ----------------------------------------------------------------------------

    def _target_concept(self, rt: _Runtime) -> str | None:
        if rt.current_item and rt.current_item.concepts:
            return rt.current_item.concepts[0]
        with self.factory() as db:
            goal = self._active_goal(db, rt)
        if goal and goal.concept_keys:
            k = rt.tracker.mastery()
            index = {c.key: i for i, c in enumerate(self.course.concepts)}
            open_ = [
                c
                for c in goal.concept_keys
                if c in index and k[index[c]] < self.settings.goals.attain_mastery
            ]
            return (open_ or goal.concept_keys)[0]
        return None

    def _rng(self, rt: _Runtime) -> random.Random:
        seed = hashlib.sha256(f"{rt.session_id}:{rt.t}:{self.settings.policy.seed}".encode())
        return random.Random(int.from_bytes(seed.digest()[:8], "big"))

    def _turn(
        self, rt: _Runtime, *, learner_text: str | None, request: Request, tags: SRLTags | None
    ) -> TurnResult:
        now = self.clock()
        state, snap = self._state(rt)
        self._close_pending(rt, state)

        target = self._target_concept(rt)
        item = rt.current_item if rt.tracker.task_active else None
        with self.factory() as db:
            rules = load_teacher_rules(db, self.course_id, self.catalogue)
            goal = self._active_goal(db, rt)
            plan = (
                db.scalars(select(m.Plan).where(m.Plan.goal_id == goal.id)).first()
                if goal
                else None
            )
            has_plan = plan is not None and any("text" in step for step in plan.steps)
        distress = detect_distress(learner_text).detected
        ctx = FilterContext(
            now=now,
            distress=distress,
            graded_item=bool(item and item.graded),
            prereq_mastery=rt.tracker.prereq_mastery(target),
            recent_unsolicited=list(rt.recent_unsolicited),
            week=self.course.week_of(now.date()),
            phase=snap.phase,
        )
        allowed = feasible_set(ctx, rules, catalogue=self.catalogue, settings=self.settings.safety)
        every = self.settings.policy.confidence_check_every
        obs = PolicyObs(
            state=tuple(state),
            phase=snap.phase,
            session_start=rt.t == 0,
            has_active_goal=goal is not None,
            has_plan=has_plan,
            consecutive_wrong=rt.tracker.consecutive_wrong,
            just_assessed=rt.tracker.just_assessed,
            quiz_completed=rt.quiz_completed,
            task_active=rt.tracker.task_active,
            graded_item=ctx.graded_item,
            item_just_presented=rt.item_just_presented,
            confidence_due=(rt.items_presented - 1) % every == 0,
            request=request,
        )
        decision = self.policy.decide(obs, allowed, self._rng(rt))
        reply, memory_ids = self._respond(
            rt,
            decision,
            allowed,
            snap,
            learner_text,
            item,
            target,
            goal.text if goal else None,
            request,
        )

        escalated = decision.action == ESCALATE or reply.escalate
        if escalated:
            reason = reply.escalation_reason or "policy"
            with self.factory.begin() as db:
                db.add(
                    m.Escalation(
                        learner_id=rt.learner_id,
                        session_id=rt.session_id,
                        reason=reason,
                        message=learner_text,
                    )
                )
        ext = TutorActionExtension(
            policy_version=decision.policy_version,
            action=decision.action,
            propensity=decision.propensity,
            filter_outcome=allowed.to_outcome(),
            retrieved_passage_ids=reply.passage_ids,
            escalated=escalated,
            prompt_version=reply.prompt_version,
            model=reply.model,
            action_probs=decision.probs,
            memory_item_ids=memory_ids,
            decision_reason=decision.reason,
        )
        self._log_and_observe(
            rt, tutor_action(rt.learner_id, rt.session_id, rt.t, ext, reply.text, self.clock())
        )
        gave_help = (
            decision.action.move in ANSWER_GIVING_MOVES
            and rt.tracker.task_active
            and not rt.tracker.answered_current
        )
        with self.factory.begin() as db:
            db.add(
                m.Transition(
                    learner_id=rt.learner_id,
                    session_id=rt.session_id,
                    t=rt.t,
                    state=state,
                    action_id=decision.action.id,
                    propensity=decision.propensity,
                    policy_version=decision.policy_version,
                )
            )
        rt.pending = _Pending(rt.t, decision.action.id, state, gave_help)
        if self.catalogue.is_unsolicited(decision.action):
            rt.recent_unsolicited.append(now)
        if reply.text:
            rt.last_tutor_text = reply.text
        result = TurnResult(
            session_id=rt.session_id,
            turn=rt.t,
            action_id=decision.action.id,
            reply=reply.text,
            why=reply.why,
            policy_reason=decision.reason,
            propensity=decision.propensity,
            escalated=escalated,
            show_support_resources=reply.show_support_resources,
            passage_ids=reply.passage_ids,
            phase=snap.phase,
            topic=(c.name if (c := self.course.concept(target) if target else None) else None),
            sources=[
                {"id": p.id, "section": p.section, "week": p.week}
                for p in rt.last_passages
                if p.id in reply.passage_ids
            ],
            answer_source=reply.answer_source,
        )
        rt.t += 1
        return result

    def _respond(
        self,
        rt: _Runtime,
        decision: Decision,
        allowed: FilterResult,
        snap: LearnerSnapshot,
        learner_text: str | None,
        item: _ItemInfo | None,
        target: str | None,
        goal_text: str | None,
        request: Request,
    ) -> tuple[AgentReply, list[int]]:
        action = decision.action
        concept = self.course.concept(target) if target else None
        query = " ".join(
            filter(
                None, [learner_text, item.text if item else None, concept.name if concept else None]
            )
        )
        spec = self.catalogue.spec(action)
        passages: list[Passage] = []
        week = self.course.week_of(self.clock().date())
        if week is not None and concept is not None and concept.week and concept.week > week:
            # Working ahead on a later topic (e.g. a practice question): its own notes are fair
            # game; material beyond that week stays hidden.
            week = concept.week
        if (
            self.rag is not None
            and query
            and (
                (spec is not None and spec.needs_rag) or (action == WAIT and request == "question")
            )
        ):
            passages = [h.passage for h in self.rag.search(query, max_week=week)]
            if concept is not None:  # notes on the topic being worked on come first
                if not any(concept.key in p.concept_keys for p in passages):
                    # Code-heavy questions can retrieve other topics' notes; add this topic's.
                    own = [
                        h.passage
                        for h in self.rag.search(concept.name, max_week=week)
                        if concept.key in h.passage.concept_keys
                    ]
                    passages = (own[:1] + passages)[: max(len(passages), 1)]
                passages.sort(key=lambda p: concept.key not in p.concept_keys)
        rt.last_passages = passages
        # Recall uses the learner's words plus the task and the active goal.
        memory_query = " ".join(filter(None, [query, goal_text]))
        recalled = (
            self.memory.recall(rt.learner_id, self.course_id, memory_query)
            if action.agent is not None
            else []
        )
        open_mode = self.settings.rag.answer_mode == "open"
        answers = action == WAIT or (spec is not None and spec.needs_rag)
        if open_mode and learner_text and request in ("question", "explanation") and answers:
            # Any question gets a genuine answer: from the notes when they cover it,
            # otherwise from general knowledge (labelled as such in the UI).
            if self.rag is not None:
                hits = self.rag.search(learner_text, max_week=week)
                passages = [h.passage for h in hits][: self.settings.rag.answer_passages]
                rt.last_passages = passages
            on_topic = bool(passages) and not self._offtopic(learner_text, passages)
            chosen = passages if on_topic else []
            return self._open_answer(rt, learner_text, chosen, item), []
        if request == "question" and learner_text and passages:
            # Whatever move was chosen (exploration included), an off-topic question gets the
            # plain 'outside this course' reply; trying to ground it would wrongly escalate.
            if self._offtopic(learner_text, passages):
                return AgentReply(action=action, text=self.settings.rag.offtopic_reply), []
            if action == WAIT:
                return self._literal_answer(learner_text, passages), []
        ctx = TurnContext(
            course_title=self.course.title,
            phase=snap.phase,
            state_summary=self._summary(rt, snap),
            learner_message=learner_text,
            memory_items=tuple(r.text for r in recalled),
            passages=tuple(passages),
            item=ItemView(item.text, item.graded, item.answer_key, item.item_type)
            if item
            else None,
            target_concept=concept.name if concept else None,
            goals=(goal_text,) if goal_text else (),
        )
        return self.team.respond(action, ctx, allowed), [r.id for r in recalled]

    def _history(self, rt: _Runtime, question: str) -> list[Message]:
        """The last few chat messages of this session (alternating, starting with the
        learner), so follow-up questions such as "why?" have their context."""
        n = self.settings.rag.history_messages
        if n == 0:
            return []
        turns: list[Message] = []
        for st in self.lrs.query(session_id=rt.session_id):
            text = st.result.response if st.result else None
            if not text:
                continue
            if st.tutor_action is not None:
                body = text.split("\n\n" + self.catalogue.why_prefix, 1)[0]
                turns.append(Message("assistant", body))
            elif st.verb.id == VERBS["commented"]:
                turns.append(Message("user", text))
        if turns and turns[-1].role == "user" and turns[-1].content == question:
            turns.pop()  # the current question is sent separately
        merged: list[Message] = []
        for msg in turns[-n:]:
            if merged and merged[-1].role == msg.role:
                merged[-1] = Message(msg.role, f"{merged[-1].content}\n{msg.content}")
            else:
                merged.append(msg)
        while merged and merged[0].role != "user":
            merged.pop(0)
        if merged and merged[-1].role == "user":
            merged.pop()  # history must end with the tutor before the new question
        return merged

    def _open_answer(
        self, rt: _Runtime, question: str, passages: list[Passage], item: _ItemInfo | None
    ) -> AgentReply:
        """A genuine answer to any question. Notes are cited when used and checked against
        the cited passage; otherwise the answer is general knowledge and labelled so."""
        graded = item is not None and item.graded
        view = ItemView(item.text, item.graded, item.answer_key, item.item_type) if item else None
        template = default_registry().get("tutor/answer")
        history = self._history(rt, question)

        def render(feedback: str | None = None) -> str:
            prompt = template.render(
                course_title=self.course.title,
                passages="\n\n".join(f"[{p.id}] {p.text}" for p in passages)
                or "(none of the course notes are about this question)",
                task=f"The learner is working on this task:\n{item.text}" if item else "",
                question=question,
                integrity=(
                    "The learner is working on a GRADED task: never give its answer, the "
                    "correct option or a full solution. Guide them with a hint instead."
                    if graded
                    else "There is no graded task in progress, so answer fully."
                ),
            )
            if feedback:
                prompt = RenderedPrompt(
                    prompt.id, prompt.version, prompt.system, f"{prompt.user}\n\n{feedback}"
                )
            return self.client.generate(
                prompt, history=history, max_tokens=self.settings.rag.answer_max_tokens
            ).strip()

        text = render()
        known = {p.id: p.text for p in passages}
        report = None
        source = "general"
        retries = self.settings.rag.answer_regenerations
        for attempt in range(retries + 1):
            if not CITATION_RE.findall(text):
                source = "general"
                break
            report = check_grounding(text, known, self.judge)
            bad = [
                c
                for c in report.checks
                if c.cited_ids and c.status in ("unknown_passage", "not_entailed")
            ]
            if not bad:
                source = "course"
                break
            source = "unverified"
            if attempt < retries:
                text = render(
                    "Some sentences cite a passage that does not support them:\n"
                    + "\n".join(f'- "{c.sentence}"' for c in bad)
                    + "\nFix them: cite only what the passage says, or drop the citation."
                )
        if source == "unverified" and self.settings.rag.unverified == "escalate":
            return AgentReply(
                action=WAIT,
                text=self.settings.rag.uncertain_reply,
                escalate=True,
                escalation_reason="grounding_failure",
                grounding=report,
            )
        integrity_reasons: tuple[str, ...] = ()
        safety = self.settings.safety
        for attempt in range(safety.integrity_regenerations + 1):
            check = integrity_check(text, view, max_code_lines=safety.max_solution_code_lines)
            if check.ok:
                break
            integrity_reasons = check.reasons
            if attempt == safety.integrity_regenerations:
                text, source = safety.integrity_fallback_reply, "general"
                break
            text = render(
                "Your previous reply broke the academic-integrity rule for this graded task ("
                + "; ".join(check.reasons)
                + "). Rewrite it so it guides with a question and reveals no answer or solution."
            )
        cited = set(CITATION_RE.findall(text))
        ids = [p.id for p in passages if p.id in cited]
        if source == "general" and passages and text:
            # Small models often use the notes without citing them: check the answer's
            # factual sentences against the notes before calling it general knowledge.
            ids = self._attribute(text, passages)
            if ids:
                source = "course"
        return AgentReply(
            action=WAIT,
            text=text,
            passage_ids=ids,
            grounding=report,
            integrity_reasons=integrity_reasons,
            answer_source=source if text else None,
        )

    def _attribute(self, text: str, passages: list[Passage], max_claims: int = 4) -> list[str]:
        """Passages that support an uncited answer: the answer counts as coming from the
        notes when at least half of its first ``max_claims`` factual sentences are entailed
        by some passage. Code blocks are left out (they are examples, not claims)."""
        detector = HeuristicClaimDetector()
        prose = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
        claims = [s for s in split_sentences(prose) if detector.is_claim(s)][:max_claims]
        if not claims:
            return []
        support: list[str] = []
        for claim in claims:
            asked = set(content_words(claim))
            for p in passages:
                if asked & set(content_words(p.text)) and self.judge.entails(p.text, claim):
                    support.append(p.id)
                    break
        if 2 * len(support) < len(claims):
            return []
        return list(dict.fromkeys(support))

    def _offtopic(self, question: str, passages: list[Passage]) -> bool:
        """Too few of the question's content words appear in the retrieved passages."""
        asked = set(content_words(question))
        covered = set(content_words(" ".join(f"{p.section or ''} {p.text}" for p in passages)))
        return not asked or len(asked & covered) / len(asked) < self.settings.rag.offtopic_overlap

    def _literal_answer(self, question: str, passages: list[Passage]) -> AgentReply:
        """WAIT: no pedagogical move, but a literal course question gets a grounded answer."""
        prompt = (
            default_registry()
            .get("rag/answer")
            .render(
                course_title=self.course.title,
                passages="\n\n".join(f"[{p.id}] {p.text}" for p in passages),
                question=question,
            )
        )
        text = self.client.generate(prompt).strip()
        report = check_grounding(text, {p.id: p.text for p in passages}, self.judge)
        if not report.ok:
            text = self.settings.rag.uncertain_reply
        return AgentReply(
            action=WAIT,
            text=text,
            passage_ids=[p.id for p in passages],
            escalate=not report.ok,
            escalation_reason=None if report.ok else "grounding_failure",
            grounding=report,
        )

    def _summary(self, rt: _Runtime, s: LearnerSnapshot) -> str:
        parts = [
            f"goal mastery {s.goal_mastery:.2f}",
            f"mean mastery {s.mean_mastery:.2f}",
            f"phase {s.phase}",
            f"calibration error {s.calibration:.2f}",
            f"plan progress {s.plan_progress:.0%}",
        ]
        if rt.tracker.consecutive_wrong:
            parts.append(f"{rt.tracker.consecutive_wrong} wrong answer(s) in a row")
        return "; ".join(parts) + "."
