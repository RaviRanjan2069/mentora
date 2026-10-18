"""Per-learner, per-session tracker: consumes logged xAPI statements one by one and keeps
everything the state builder needs. It can be rebuilt at any time by replaying the log."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Mapping, Sequence

import numpy as np

from mentora.config.settings import LearnerModelSettings
from mentora.course import CourseSpec
from mentora.learner_model.calibration import CalibrationTracker
from mentora.learner_model.engagement import Engagement
from mentora.learner_model.hmm_tactics import TacticHMM
from mentora.learner_model.kt.data import Interaction
from mentora.learner_model.kt.mastery import MasteryModel
from mentora.learner_model.requests import Request
from mentora.learner_model.srl_phase import PhaseContext, infer_phase
from mentora.learner_model.srl_tagger import INDICATORS, SRLTags
from mentora.learner_model.state import LearnerSnapshot, build_state
from mentora.learner_model.tactics import TACTIC_INDEX, code_statement
from mentora.logging_xapi.statements import (
    EXT_ATTEMPT,
    EXT_CONFIDENCE,
    EXT_HINTS,
    EXT_SRL_TAGS,
    VERBS,
    Statement,
)
from mentora.policy.catalogue import Phase

_DURATION_RE = re.compile(r"PT(\d+(?:\.\d+)?)S")
_SRL_AGENTS = {"Planner", "Monitor", "ReflectionCoach"}
_LEARNER_SRL = set(INDICATORS) - {"help_request"}


class LearnerTracker:
    def __init__(
        self,
        course: CourseSpec,
        cfg: LearnerModelSettings,
        mastery_model: MasteryModel,
        hmm: TacticHMM,
        item_concepts: Mapping[int, Sequence[str]],
        prior_history: Sequence[Interaction] = (),
    ) -> None:
        self.course = course
        self.cfg = cfg
        self.mastery_model = mastery_model
        self.hmm = hmm
        self.item_concepts = item_concepts
        self.concept_index = {c.key: i for i, c in enumerate(course.concepts)}
        self.history: list[Interaction] = list(prior_history)
        self.alpha: np.ndarray | None = None
        self.tags_window: deque[SRLTags] = deque(maxlen=cfg.indicator_window)
        self.last_tags: SRLTags | None = None
        self.calibration = CalibrationTracker(cfg.calibration_eta, cfg.calibration_init)
        self.session_turn = 0
        self.current_item: int | None = None
        self.task_active = False
        self.just_assessed = False
        self.consecutive_wrong = 0
        self.items_started = 0
        self.hints_before_attempt = 0
        self._answered_current = False
        self.learner_messages = 0
        self.answer_requests = 0
        self.learner_srl_actions = 0
        self.tutor_srl_actions = 0

    # --- updates ---------------------------------------------------------------------------

    def start_item(self, item_id: int) -> None:
        self.current_item = item_id
        self.task_active = True
        self.items_started += 1
        self._answered_current = False

    def observe(
        self, st: Statement, tags: SRLTags | None = None, request: Request | None = None
    ) -> None:
        verb = st.verb.id
        self.just_assessed = False
        if (
            tags is None
            and st.result
            and st.result.extensions
            and EXT_SRL_TAGS in st.result.extensions
        ):
            tags = SRLTags.model_validate(st.result.extensions[EXT_SRL_TAGS])

        tactic = code_statement(st, tags.model_dump() if tags else None)
        if tactic is not None:
            self.alpha = self.hmm.step(self.alpha, TACTIC_INDEX[tactic])

        if verb == VERBS["answered"]:
            self._observe_answer(st)
        elif verb == VERBS["commented"]:
            self.learner_messages += 1
            if tags is not None:
                self.tags_window.append(tags)
                self.last_tags = tags
                if any(getattr(tags, k) for k in _LEARNER_SRL):
                    self.learner_srl_actions += 1
            if request == "answer":
                self.answer_requests += 1
            if request in ("hint", "answer") and self.task_active and not self._answered_current:
                self.hints_before_attempt += 1
        elif verb == VERBS["asked"]:
            if self.task_active and not self._answered_current:
                self.hints_before_attempt += 1
        elif verb == VERBS["received"]:
            ext = st.tutor_action
            if ext is not None and ext.action.agent in _SRL_AGENTS:
                self.tutor_srl_actions += 1
        if verb != VERBS["received"]:
            self.session_turn += 1

    def _observe_answer(self, st: Statement) -> None:
        res = st.result
        ext = (res.extensions if res else None) or {}
        correct = bool(res and res.success)
        item_id = st.item_id
        keys = self.item_concepts.get(item_id, ()) if item_id is not None else ()
        concept = next((self.concept_index[k] for k in keys if k in self.concept_index), None)
        duration = _DURATION_RE.fullmatch(res.duration) if res and res.duration else None
        if concept is not None:
            self.history.append(
                Interaction(
                    concept,
                    int(correct),
                    float(duration.group(1)) if duration else 10.0,
                    int(ext.get(EXT_HINTS, 0)),
                    int(ext.get(EXT_ATTEMPT, 1)),
                )
            )
        if EXT_CONFIDENCE in ext:
            self.calibration.update(float(ext[EXT_CONFIDENCE]), correct)
        self.consecutive_wrong = 0 if correct else self.consecutive_wrong + 1
        self._answered_current = True
        self.just_assessed = True
        if correct:
            self.task_active = False
            self.current_item = None

    # --- reads -----------------------------------------------------------------------------

    @property
    def answered_current(self) -> bool:
        """Has the learner answered the current item at least once?"""
        return self._answered_current

    def mastery(self) -> np.ndarray:
        return self.mastery_model.mastery(self.history, len(self.course.concepts))

    def concept_mastery(self, keys: Sequence[str]) -> float | None:
        k = self.mastery()
        idx = [self.concept_index[c] for c in keys if c in self.concept_index]
        return float(np.mean(k[idx])) if idx else None

    def prereq_mastery(self, concept_key: str | None) -> float | None:
        """Lowest mastery among the concept's prerequisites; None if it has none."""
        if concept_key is None:
            return None
        spec = next((c for c in self.course.concepts if c.key == concept_key), None)
        if spec is None or not spec.prereqs:
            return None
        k = self.mastery()
        return float(min(k[self.concept_index[p]] for p in spec.prereqs))

    def phase(self, has_active_goal: bool) -> Phase:
        ctx = PhaseContext(self.session_turn, self.task_active, self.just_assessed, has_active_goal)
        return infer_phase(ctx, self.last_tags)

    def snapshot(
        self,
        *,
        goal_concepts: Sequence[str],
        has_active_goal: bool,
        plan_progress: float,
        engagement: Engagement,
    ) -> LearnerSnapshot:
        k = self.mastery()
        goal = self.concept_mastery(goal_concepts)
        counts = {name: sum(getattr(t, name) for t in self.tags_window) for name in INDICATORS}
        srl_total = self.learner_srl_actions + self.tutor_srl_actions
        return LearnerSnapshot(
            goal_mastery=goal if goal is not None else float(k.mean()),
            mean_mastery=float(k.mean()),
            phase=self.phase(has_active_goal),
            alpha=self.alpha if self.alpha is not None else self.hmm.startprob,
            indicator_counts=counts,
            calibration=self.calibration.value,
            engagement=engagement,
            plan_progress=plan_progress,
            learner_initiated_share=self.learner_srl_actions / srl_total if srl_total else 0.0,
            hint_before_attempt_rate=self.hints_before_attempt / max(self.items_started, 1),
            answer_request_rate=self.answer_requests / max(self.learner_messages, 1),
        )

    def state_vector(self, snapshot: LearnerSnapshot) -> list[float]:
        return build_state(snapshot, self.cfg, self.cfg.indicator_window)
