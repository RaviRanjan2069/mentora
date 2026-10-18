"""Read-only analytics for the learner home page and the teacher console.

Every number here is computed from the logs with a stated definition (see the docstrings),
so the UI never shows a figure that cannot be explained. Nothing here feeds the policy.
"""

from __future__ import annotations

import itertools
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import mean
from typing import Any

from mentora.config.settings import Settings
from mentora.course import item_concept_keys
from mentora.db import ASC, DESC, Document, Store
from mentora.db import models as m
from mentora.learner_model.calibration import CalibrationTracker
from mentora.learner_model.engagement import engagement
from mentora.learner_model.kt.data import Interaction
from mentora.learner_model.srl_tagger import trace_reflection_quality
from mentora.logging_xapi.statements import EXT_CONFIDENCE, EXT_SRL_TAGS, VERBS, Statement
from mentora.orchestrator.turn import Orchestrator

SIMULATED_PREFIX = "lrn_sim_"
_REFLECTIVE = ("self_evaluation", "attribution", "adaptation_intent")


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _events(db: Store, learner_id: str | None = None) -> list[Statement]:
    rows = db.values(
        m.Event,
        ["statement"],
        {} if learner_id is None else {"learner_id": learner_id},
        sort=[("timestamp", ASC), ("seq", ASC)],
    )
    return [Statement.model_validate(raw) for (raw,) in rows]


def _column(db: Store, model: type[Document], field: str, filter: dict[str, Any]) -> list[Any]:
    return [v for (v,) in db.values(model, [field], filter)]


def study_streak(days_with_sessions: set[date], today: date) -> int:
    """Consecutive days with at least one session, ending today (or yesterday)."""
    day = today if today in days_with_sessions else today - timedelta(days=1)
    streak = 0
    while day in days_with_sessions:
        streak += 1
        day -= timedelta(days=1)
    return streak


def accuracy(answers: list[Statement], start: datetime, end: datetime) -> float | None:
    window = [a for a in answers if start <= _aware(a.timestamp) < end]
    if not window:
        return None
    return sum(bool(a.result and a.result.success) for a in window) / len(window)


def active_hours(times: list[datetime], idle_minutes: float) -> float:
    """Sum of gaps between consecutive events that are shorter than the idle threshold."""
    ts = sorted(_aware(t) for t in times)
    limit = idle_minutes * 60
    total = sum(gap for a, b in itertools.pairwise(ts) if (gap := (b - a).total_seconds()) <= limit)
    return total / 3600


def activity_calendar(times: list[datetime], today: date, days: int = 84) -> list[dict[str, Any]]:
    """Logged events per calendar day (UTC) for the last ``days`` days, oldest first."""
    counts = Counter(_aware(t).date() for t in times)
    start = today - timedelta(days=days - 1)
    return [
        {"date": d.isoformat(), "events": counts.get(d, 0)}
        for d in (start + timedelta(days=i) for i in range(days))
    ]


@dataclass(frozen=True)
class SRLProgress:
    """Each phase score is in [0, 1].

    * forethought: mean of (share of sessions where a goal was set, mean goal clarity)
    * performance: mean of (1 - calibration error, accuracy over the last 30 answers)
    * reflection: mean of (share of sessions with a reflective message, mean reflection quality)
    """

    forethought: float
    performance: float
    reflection: float
    has_data: bool

    @property
    def overall(self) -> float:
        return (self.forethought + self.performance + self.reflection) / 3


def srl_progress(
    db: Store, learner_id: str, events: list[Statement], settings: Settings
) -> SRLProgress:
    sessions = _column(db, m.Session, "id", {"learner_id": learner_id})
    if not sessions:
        return SRLProgress(0.0, 0.0, 0.0, False)
    goals = db.find(m.Goal, {"learner_id": learner_id})
    goal_sessions = {g.session_id for g in goals if g.session_id}
    smart = [g.smart_score for g in goals if g.smart_score is not None]
    forethought = mean(
        [len(goal_sessions & set(sessions)) / len(sessions), mean(smart) if smart else 0.0]
    )

    cfg = settings.learner_model
    calib = CalibrationTracker(cfg.calibration_eta, cfg.calibration_init)
    answers = [e for e in events if e.verb.id == VERBS["answered"]]
    for a in answers:
        ext = a.result.extensions if a.result and a.result.extensions else {}
        if EXT_CONFIDENCE in ext:
            calib.update(float(ext[EXT_CONFIDENCE]), bool(a.result and a.result.success))
    recent = answers[-30:]
    parts = []
    if calib.points:
        parts.append(1 - calib.value)
    if recent:
        parts.append(sum(bool(a.result and a.result.success) for a in recent) / len(recent))
    performance = mean(parts) if parts else 0.0

    reflective: list[Statement] = []
    for e in events:
        ext = e.result.extensions if e.result and e.result.extensions else {}
        tags = ext.get(EXT_SRL_TAGS) or {}
        if e.verb.id == VERBS["commented"] and any(tags.get(k) for k in _REFLECTIVE):
            reflective.append(e)
    refl_sessions = {e.session_id for e in reflective}
    quality = [trace_reflection_quality(e.result.response or "") for e in reflective if e.result]
    reflection = mean(
        [len(refl_sessions & set(sessions)) / len(sessions), mean(quality) if quality else 0.0]
    )
    return SRLProgress(forethought, performance, reflection, True)


def _history(orch: Orchestrator, db: Store, learner_id: str) -> list[Interaction]:
    return orch.learner_history(db, learner_id, "", item_concept_keys(db, orch.course_id))


def _activity_line(st: Statement, items: dict[int, str]) -> tuple[str, str] | None:
    verb = st.verb.id
    if verb == VERBS["answered"] and st.item_id is not None:
        ok = bool(st.result and st.result.success)
        return (
            "quiz",
            f"Answered: {items.get(st.item_id, 'a practice item')} "
            f"({'right' if ok else 'not yet'})",
        )
    if verb == VERBS["launched"] and st.item_id is not None:
        return "practice", f"Practised: {items.get(st.item_id, 'a practice item')}"
    if verb == VERBS["experienced"]:
        name = (
            st.object_.definition.name.get("en-US")
            if st.object_.definition and st.object_.definition.name
            else None
        )
        return "resource", f"Viewed resource: {name or 'course material'}"
    if verb == VERBS["commented"]:
        return "chat", "Chatted with the tutor"
    if verb == VERBS["terminated"]:
        return "session", "Finished a study session"
    return None


def learner_home(db: Store, orch: Orchestrator, learner_id: str, now: datetime) -> dict[str, Any]:
    s = orch.settings
    events = _events(db, learner_id)
    answers = [e for e in events if e.verb.id == VERBS["answered"]]
    starts = _column(db, m.Session, "started_at", {"learner_id": learner_id})
    week = now - timedelta(days=7)
    history = _history(orch, db, learner_id)
    k = orch.mastery_model.mastery(history, len(orch.course.concepts))
    practised = {x.concept for x in history}
    mastered = [i for i in range(len(k)) if i in practised and k[i] >= s.goals.attain_mastery]
    srl = srl_progress(db, learner_id, events, s)

    items = {
        i.id: i.text.split("\n")[0][:70] for i in db.find(m.Item, {"course_id": orch.course_id})
    }
    activity = []
    for st in reversed(events):
        line = _activity_line(st, items)
        if line:
            activity.append({"kind": line[0], "text": line[1], "at": _aware(st.timestamp)})
        if len(activity) == 6:
            break

    moves = Counter(
        st.tutor_action.action.move
        for st in events[-200:]
        if st.tutor_action is not None and st.tutor_action.action.agent is not None
    )
    strategy = None
    if moves:
        move = moves.most_common(1)[0][0]
        spec = orch.catalogue.moves[move]
        strategy = {
            "title": move.replace("_", " ").capitalize(),
            "agent": spec.agent,
            "description": spec.description,
            "why": spec.why,
        }

    return {
        "stats": {
            "streak_days": study_streak({_aware(t).date() for t in starts}, now.date()),
            "topics_completed": len(mastered),
            "topics_total": len(orch.course.concepts),
            "quiz_average": accuracy(answers, week, now),
            "quiz_average_previous": accuracy(answers, week - timedelta(days=7), week),
            "learning_hours_week": round(
                active_hours(
                    [_aware(e.timestamp) for e in events if _aware(e.timestamp) >= week],
                    s.learner_model.idle_minutes,
                ),
                2,
            ),
        },
        "srl": {
            "overall": srl.overall,
            "forethought": srl.forethought,
            "performance": srl.performance,
            "reflection": srl.reflection,
            "has_data": srl.has_data,
        },
        "strategy": strategy,
        "activity": activity,
        "next_steps": next_steps(db, orch, k, practised),
        "calendar": activity_calendar([e.timestamp for e in events], now.date()),
    }


def display_id(learner_id: str) -> str:
    """Short pseudonym shown in the teacher views."""
    return learner_id.removeprefix("lrn_")[:12]


def student_detail(
    db: Store, orch: Orchestrator, learner_id: str, now: datetime
) -> dict[str, Any] | None:
    """Everything the teacher console shows for one learner: the learner's own home-page
    figures plus mastery per concept, recent goals and session count."""
    if db.get(m.Learner, learner_id) is None:
        return None
    data = learner_home(db, orch, learner_id, now)
    history = _history(orch, db, learner_id)
    k = orch.mastery_model.mastery(history, len(orch.course.concepts))
    practised = {x.concept for x in history}
    goals = db.find(m.Goal, {"learner_id": learner_id}, sort=[("id", DESC)], limit=8)
    sessions = db.count(m.Session, {"learner_id": learner_id})
    return {
        **data,
        "id": learner_id,
        "learner": display_id(learner_id),
        "simulated": learner_id.startswith(SIMULATED_PREFIX),
        "sessions": int(sessions or 0),
        "mastery": [
            {
                "concept": c.name,
                "key": c.key,
                "mastery": round(float(k[i]), 3),
                "practised": i in practised,
            }
            for i, c in enumerate(orch.course.concepts)
        ],
        "goals": [
            {
                "text": g.text,
                "status": g.status,
                "smart_score": g.smart_score,
                "created_at": _aware(g.created_at),
            }
            for g in goals
        ],
    }


def next_steps(db: Store, orch: Orchestrator, k: Any, practised: set[int]) -> list[dict[str, Any]]:
    """Up to three 'frontier' concepts: not yet mastered, prerequisites mastered (or none),
    earliest course week first. Each gets a practice item if one exists, else reading."""
    s = orch.settings
    index = {c.key: i for i, c in enumerate(orch.course.concepts)}

    def ok(key: str) -> bool:
        return bool(k[index[key]] >= s.goals.attain_mastery and index[key] in practised)

    concept_items: dict[str, list[int]] = defaultdict(list)
    passages = db.find(m.CorpusPassage, {"course_id": orch.course_id})
    for item_id, keys in item_concept_keys(db, orch.course_id).items():
        for key in keys:
            concept_items[key].append(item_id)
    out: list[dict[str, Any]] = []
    for c in sorted(orch.course.concepts, key=lambda c: (c.week or 99, index[c.key])):
        if ok(c.key) or not all(ok(p) for p in c.prereqs):
            continue
        if concept_items[c.key]:
            out.append(
                {
                    "kind": "practice",
                    "title": f"Practice: {c.name}",
                    "concept": c.key,
                    "detail": f"{len(concept_items[c.key])} question(s)",
                    "item_ids": concept_items[c.key],
                }
            )
        else:
            passage = passages
            match = next((p for p in passage if c.key in (p.concept_keys or [])), None)
            out.append(
                {
                    "kind": "read",
                    "title": f"Read: {c.name}",
                    "concept": c.key,
                    "detail": match.section if match else "course material",
                    "passage_id": match.id if match else None,
                }
            )
        if len(out) == 3:
            break
    return out


# --- teacher -------------------------------------------------------------------------------


def students_summary(db: Store, orch: Orchestrator, now: datetime) -> list[dict[str, Any]]:
    """One row per learner with at least one session.

    At risk: dropout risk >= 0.5, or accuracy < 40% over at least 5 answers, or an open
    distress escalation."""
    s = orch.settings
    # Learners with at least one session (sessions cascade with their learner).
    learners = sorted(db.distinct(m.Session, "learner_id"))
    out = []
    for lid in learners:
        starts = _column(db, m.Session, "started_at", {"learner_id": lid})
        times = _column(db, m.Event, "timestamp", {"learner_id": lid})
        eng = engagement(
            [_aware(t) for t in starts], [_aware(t) for t in times], [], now, s.learner_model
        )
        answers = [st for st in _events(db, lid) if st.verb.id == VERBS["answered"]]
        acc = (
            sum(bool(a.result and a.result.success) for a in answers) / len(answers)
            if answers
            else None
        )
        hist = _history(orch, db, lid)
        k = orch.mastery_model.mastery(hist, len(orch.course.concepts))
        open_distress = db.count(
            m.Escalation, {"learner_id": lid, "status": "open", "reason": "distress"}
        )
        open_any = db.count(m.Escalation, {"learner_id": lid, "status": "open"})
        at_risk = (
            eng.dropout_risk >= 0.5
            or (acc is not None and len(answers) >= 5 and acc < 0.4)
            or open_distress > 0
        )
        out.append(
            {
                "id": lid,
                "learner": display_id(lid),
                "simulated": lid.startswith(SIMULATED_PREFIX),
                "sessions": len(starts),
                "last_active": max(_aware(t) for t in times) if times else None,
                "mean_mastery": round(float(k.mean()), 3),
                "quiz_average": round(acc, 3) if acc is not None else None,
                "answers": len(answers),
                "dropout_risk": round(eng.dropout_risk, 3),
                "at_risk": bool(at_risk),
                "open_escalations": int(open_any),
            }
        )

    def order(r: dict[str, Any]) -> tuple[bool, float]:
        last: datetime | None = r["last_active"]
        return (not r["at_risk"], -(last.timestamp() if last else 0.0))

    out.sort(key=order)
    return out


def class_overview(db: Store, orch: Orchestrator, now: datetime) -> dict[str, Any]:
    """Stat cards, weekly progress, topic accuracy and recent activity for the course.

    * average score: share of correct answers over all logged answers
    * weekly goal completion: goals created in that course week that were attained
    """
    students = students_summary(db, orch, now)
    week_ago = now - timedelta(days=7)
    events = _events(db)
    answers = [e for e in events if e.verb.id == VERBS["answered"]]
    item_keys = item_concept_keys(db, orch.course_id)

    weekly: dict[int, dict[str, list[float]]] = defaultdict(lambda: {"score": [], "goal": []})
    for a in answers:
        wk = orch.course.week_of(_aware(a.timestamp).date())
        if wk is not None:
            weekly[wk]["score"].append(1.0 if a.result and a.result.success else 0.0)
    for g in db.find(m.Goal):
        wk = orch.course.week_of(_aware(g.created_at).date())
        if wk is not None:
            weekly[wk]["goal"].append(1.0 if g.status == "attained" else 0.0)
    weeks = [
        {
            "week": wk,
            "average_score": round(mean(v["score"]), 3) if v["score"] else None,
            "goal_completion": round(mean(v["goal"]), 3) if v["goal"] else None,
            "answers": len(v["score"]),
        }
        for wk, v in sorted(weekly.items())
    ]

    per_concept: dict[str, list[float]] = defaultdict(list)
    for a in answers:
        for key in item_keys.get(a.item_id or -1, []):
            per_concept[key].append(1.0 if a.result and a.result.success else 0.0)
    names = {c.key: c.name for c in orch.course.concepts}
    topics = sorted(
        (
            {
                "concept": names.get(key, key),
                "key": key,
                "accuracy": round(mean(v), 3),
                "answers": len(v),
            }
            for key, v in per_concept.items()
        ),
        key=lambda t: float(t["accuracy"]),  # type: ignore[arg-type]
        reverse=True,
    )

    items = {
        i.id: i.text.split("\n")[0][:60] for i in db.find(m.Item, {"course_id": orch.course_id})
    }
    activity = []
    for st in reversed(events):
        line = _activity_line(st, items)
        if line:
            activity.append(
                {
                    "learner": display_id(st.learner_id),
                    "activity": line[1],
                    "at": _aware(st.timestamp),
                }
            )
        if len(activity) == 8:
            break

    scored = [s["quiz_average"] for s in students if s["quiz_average"] is not None]
    return {
        "stats": {
            "total_students": len(students),
            "active_week": sum(
                1 for s in students if s["last_active"] and s["last_active"] >= week_ago
            ),
            "average_score": round(mean(scored), 3) if scored else None,
            "at_risk": sum(1 for s in students if s["at_risk"]),
            "simulated_students": sum(1 for s in students if s["simulated"]),
        },
        "weekly": weeks,
        "topics": topics,
        "activity": activity,
    }
