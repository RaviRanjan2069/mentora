"""End-of-session memory update.

1. Session return G vs the learner's running mean: every memory item used in the session
   gets n_plus (G >= mean) or n_minus; q = (n_plus + 1) / (n_plus + n_minus + 2).
2. A reflector (LLM, or a heuristic without an LLM) proposes candidate insights.
3. A deterministic curator scores each candidate on four criteria: specific, evidenced in
   the transcript, non-sensitive, not instruction-like. Sensitive or instruction-like
   candidates are vetoed (score 0) whatever else they score; admit if score >= gate.
4. Merge into an existing item when cosine > merge threshold; prune items that keep
   failing (n_minus - n_plus > delta, or q < q_min) and items past retention.
Course-scope candidates go to the teacher review queue, never straight into memory.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from mentora.config.settings import Settings
from mentora.course import load_course
from mentora.db import ASC, Store, StoreFactory
from mentora.db import models as m
from mentora.learner_model.srl_tagger import trace_tags
from mentora.llm.client import LLMClient
from mentora.llm.prompts import default_registry
from mentora.llm.types import LLMError
from mentora.logging_xapi.lrs_client import SqlLRSClient
from mentora.logging_xapi.statements import VERBS
from mentora.memory.recall import recall
from mentora.memory.service import RecalledItem
from mentora.memory.store import purge_expired, quality, record_outcome
from mentora.rag.embeddings import Embedder, make_embedder
from mentora.rag.text import content_words

_INSTRUCTION_RE = re.compile(
    r"\b(always|never|must|from now on|remember( that|:)?|ignore|override|disregard|"
    r"you (should|must|will|need to)|the (tutor|assistant|ai|system) (should|must|will)|"
    r"(give|tell|show) (me|them|the learner) the (full |complete )?(answer|solution|code)|"
    r"do not (ask|question)|instructions?|system prompt|jailbreak)\b",
    re.IGNORECASE,
)
_SENSITIVE_RE = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.]+|(\+?\d[\d\s-]{7,}\d)|\b(password|address|aadhaar|passport)\b|"
    r"\b(depress\w*|anxiety|anxious|suicid\w*|self[- ]?harm|diagnos\w*|medication|therapy|"
    r"pregnan\w*|disabilit\w*|religio\w*|caste|sexual\w*|boyfriend|girlfriend|divorce|"
    r"parents?|family|illness|sick)\b",
    re.IGNORECASE,
)


class Candidate(BaseModel):
    text: str = Field(min_length=1, max_length=400)
    scope: Literal["learner", "course"] = "learner"
    kind: Literal["goal", "misconception", "what_worked", "preference", "other"] = "other"
    evidence: str = ""


class ReflectorOutput(BaseModel):
    candidates: list[Candidate] = Field(default_factory=list)


@dataclass(frozen=True)
class CuratorScore:
    specific: float
    evidenced: float
    non_sensitive: float
    not_instruction: float
    weights: tuple[float, float, float, float] = (0.45, 0.25, 0.15, 0.15)

    @property
    def total(self) -> float:
        # Vetoes: no fabricated (unevidenced), sensitive or instruction-like memories.
        if not (self.evidenced and self.non_sensitive and self.not_instruction):
            return 0.0
        parts = (self.specific, self.evidenced, self.non_sensitive, self.not_instruction)
        return sum(w * x for w, x in zip(self.weights, parts, strict=True))


@dataclass
class CurationReport:
    session_return: float = 0.0
    running_mean: float = 0.0
    updated_items: list[int] = field(default_factory=list)
    admitted: list[str] = field(default_factory=list)
    queued_for_teacher: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    rejected: list[tuple[str, float]] = field(default_factory=list)
    pruned: list[int] = field(default_factory=list)


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", s.lower()).split())


def curate(
    c: Candidate,
    learner_text: str,
    course_terms: set[str],
    min_words: int,
    weights: tuple[float, float, float, float] = (0.45, 0.25, 0.15, 0.15),
) -> CuratorScore:
    words = c.text.split()
    cw = set(content_words(c.text))
    specific = float(
        len(words) >= min_words and (bool(cw & course_terms) or bool(re.search(r"\d", c.text)))
    )
    transcript = _norm(learner_text)
    quote_ok = bool(c.evidence.strip()) and _norm(c.evidence) in transcript
    overlap = len(cw & set(transcript.split())) / len(cw) if cw else 0.0
    evidenced = float(quote_ok and overlap >= 0.3)
    combined = f"{c.text} {c.evidence}"
    non_sensitive = float(not _SENSITIVE_RE.search(combined))
    not_instruction = float(not _INSTRUCTION_RE.search(c.text))
    return CuratorScore(specific, evidenced, non_sensitive, not_instruction, weights)


def heuristic_reflector(learner_messages: list[str], max_candidates: int) -> list[Candidate]:
    """No-LLM reflector: goals and self-reported lessons, quoted from the learner."""
    out: list[Candidate] = []
    for msg in learner_messages:
        tags = trace_tags(msg)
        if tags.goal_stated:
            out.append(Candidate(text=f"Set the goal: {msg}", kind="goal", evidence=msg))
        elif tags.attribution or tags.adaptation_intent:
            out.append(Candidate(text=f"Reflected: {msg}", kind="what_worked", evidence=msg))
    return out[-max_candidates:]


class ReflectiveMemory:
    """MemoryService backed by the memory_items table."""

    def __init__(
        self,
        settings: Settings,
        session_factory: StoreFactory,
        *,
        client: LLMClient | None = None,
        embedder: Embedder | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.factory = session_factory
        self.client = client
        self.embedder = embedder or make_embedder(settings)
        self.course = load_course(settings.app.concepts_file)
        self._now: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
        mode = settings.memory.reflector_mode
        if mode == "auto":
            mode = "llm" if settings.llm.backend == "hosted" else "heuristic"
        self.reflector_mode = mode if client is not None else "heuristic"
        self.course_terms = {
            w for c in self.course.concepts for p in c.phrases for w in content_words(p)
        }

    # --- MemoryService ------------------------------------------------------------------------

    def recall(self, learner_id: str, course_id: int, query: str) -> list[RecalledItem]:
        if not query.strip():
            return []
        cfg = self.settings.memory
        emb = self.embedder.embed([query])[0]
        with self.factory() as db:
            return recall(
                db,
                emb,
                learner_id,
                course_id,
                k=cfg.recall_k,
                half_life_days=cfg.recency_half_life_days,
                now=self._now(),
            )

    def end_session(self, session_id: str) -> None:
        self.curate_session(session_id)

    # --- the job ------------------------------------------------------------------------------

    def curate_session(self, session_id: str) -> CurationReport:
        cfg = self.settings.memory
        now = self._now()
        report = CurationReport()
        with self.factory() as db:
            sess = db.get(m.Session, session_id)
            if sess is None:
                raise ValueError(f"unknown session {session_id}")
            learner_id, course_id = sess.learner_id, sess.course_id
        statements = SqlLRSClient(self.factory).query(session_id=session_id)
        learner_msgs = [
            s.result.response
            for s in statements
            if s.verb.id == VERBS["commented"] and s.result and s.result.response
        ]
        transcript_lines = []
        used: set[int] = set()
        for s in statements:
            if s.verb.id == VERBS["commented"] and s.result and s.result.response:
                transcript_lines.append(f"Learner: {s.result.response}")
            ext = s.tutor_action
            if ext is not None:
                used.update(ext.memory_item_ids)
                if s.result and s.result.response:
                    transcript_lines.append(f"Tutor: {s.result.response}")

        with self.factory.begin() as db:
            report.session_return, report.running_mean = self._returns(db, session_id, learner_id)
            helped = report.session_return >= report.running_mean
            for item_id in sorted(used):
                item = db.get(m.MemoryItem, item_id)
                if item is not None:
                    record_outcome(item, helped, now)
                    report.updated_items.append(item_id)

        candidates = self._reflect(learner_msgs, "\n".join(transcript_lines))
        learner_text = "\n".join(learner_msgs)
        with self.factory.begin() as db:
            for c in candidates:
                score = curate(
                    c,
                    learner_text,
                    self.course_terms,
                    cfg.min_specific_words,
                    cfg.curator_weights,
                )
                if score.total < cfg.curator_gate:
                    report.rejected.append((c.text, score.total))
                    continue
                emb = self.embedder.embed([c.text])[0]
                twin = self._near_duplicate(db, emb, learner_id, course_id, c.scope)
                if twin is not None:
                    twin.last_used_at = now
                    report.merged.append(c.text)
                    continue
                status = "pending_review" if c.scope == "course" else "active"
                db.add(
                    m.MemoryItem(
                        scope=c.scope,
                        learner_id=learner_id if c.scope == "learner" else None,
                        course_id=course_id,
                        text=c.text,
                        embedding=emb,
                        n_plus=0,
                        n_minus=0,
                        quality=quality(0, 0),
                        status=status,
                        source_session_id=session_id,
                        created_at=now,
                    )
                )
                (report.queued_for_teacher if c.scope == "course" else report.admitted).append(
                    c.text
                )
            report.pruned = self._prune(db, learner_id, course_id)
            purge_expired(db, self.settings.privacy.retention_days, now)
        return report

    def _returns(self, db: Store, session_id: str, learner_id: str) -> tuple[float, float]:
        rows = db.values(m.Transition, ["session_id", "reward"], {"learner_id": learner_id})
        per: dict[str, float] = {}
        for sid, r in rows:
            per[sid] = per.get(sid, 0.0) + (r or 0.0)
        current = per.pop(session_id, 0.0)
        return current, (sum(per.values()) / len(per) if per else 0.0)

    def _reflect(self, learner_msgs: list[str], transcript: str) -> list[Candidate]:
        n = self.settings.memory.max_candidates
        if not learner_msgs:
            return []
        if self.reflector_mode == "llm" and self.client is not None:
            prompt = (
                default_registry()
                .get("memory/reflector")
                .render(max_candidates=n, course_title=self.course.title, transcript=transcript)
            )
            try:
                return self.client.generate(prompt, ReflectorOutput).candidates[:n]
            except LLMError:
                pass
        return heuristic_reflector(learner_msgs, n)

    def _near_duplicate(
        self, db: Store, emb: list[float], learner_id: str, course_id: int, scope: str
    ) -> m.MemoryItem | None:
        q = np.asarray(emb)
        filter: dict[str, object] = {
            "course_id": course_id,
            "scope": scope,
            "status": {"$in": ["active", "pending_review"]},
        }
        if scope == "learner":
            filter["learner_id"] = learner_id
        for row in db.find(m.MemoryItem, filter, sort=[("id", ASC)]):
            if row.embedding is None:
                continue
            v = np.asarray(row.embedding)
            cos = float(q @ v / ((np.linalg.norm(q) * np.linalg.norm(v)) or 1.0))
            if cos > self.settings.memory.merge_cosine:
                return row
        return None

    def _prune(self, db: Store, learner_id: str, course_id: int) -> list[int]:
        cfg = self.settings.memory
        pruned = []
        for row in db.find(
            m.MemoryItem,
            {"learner_id": learner_id, "course_id": course_id, "status": "active"},
            sort=[("id", ASC)],
        ):
            if row.n_minus - row.n_plus > cfg.prune_delta or row.quality < cfg.q_min:
                row.status = "pruned"
                pruned.append(row.id)
        return pruned
