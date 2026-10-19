"""Learning roadmaps: a goal turned into a week-by-week plan from basics to advanced (D44).

Roadmaps for the subjects Mentora has question banks for come from hand-written templates
(``mentora/subjects_data/roadmaps.json``): units of topics with a practice link to the subject's
question bank and a hands-on exercise, ending with a project. The student's level shortens or
skips the basics; the pace puts one or two units in a week. Each week gets tasks:

* study - the week's topics (ticked by the student);
* practice - 10 questions on the week's bank topics in My Learning, done automatically at 60%
  or better once at least 10 are answered after the roadmap was made;
* exercise / project - hands-on work (ticked by the student);
* checkpoint - at the end of each stage, 15 answers on the stage's topics at 70% or better.

``adapt`` keeps the plan in step with the student's My Learning results: a topic from the
weeks so far that the student scores below 60% on (3+ answers) gets a review task in the current
week; future
weeks whose topics the student already masters become optional; when the student falls two or
more weeks behind the dates, the dates move. Every change is logged with its reason.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from functools import cache
from importlib import resources
from typing import Any

from pydantic import BaseModel, Field

from mentora import practice as pr
from mentora.db import models as m

LEVELS = {"beginner": "New to it", "some": "Know the basics", "experienced": "Experienced"}
PACES = {"steady": "One topic block a week", "fast": "Two topic blocks a week"}
PRACTICE_TARGET, PRACTICE_PASS = 10, 0.6
CHECKPOINT_TARGET, CHECKPOINT_PASS = 15, 0.7
REVIEW_BELOW, SKIP_FROM, SKIP_EVIDENCE = 0.6, 0.8, 5
STAGES = ("Basics", "Intermediate", "Advanced", "Project")


class RoadmapError(ValueError):
    """A request that cannot be done; the message is safe to show."""


@cache
def templates() -> dict[str, dict[str, Any]]:
    raw = resources.files("mentora.subjects_data").joinpath("roadmaps.json").read_text("utf-8")
    data: dict[str, dict[str, Any]] = json.loads(raw)
    return data


def match_subject(goal: str) -> str | None:
    """The template subject a goal is about ("learn core java" -> "Java"), by the longest alias
    found as whole words."""
    text = " " + re.sub(r"[^a-z0-9+#]+", " ", goal.casefold()) + " "
    best: tuple[int, str] | None = None
    for subject, spec in templates().items():
        for alias in [subject.casefold(), *spec["aliases"]]:
            if f" {alias} " in text and (best is None or len(alias) > best[0]):
                best = (len(alias), subject)
    return best[1] if best else None


def clean_goal(raw: str) -> str:
    goal = " ".join(raw.split())
    if not 3 <= len(goal) <= 200:
        raise RoadmapError(
            "Describe your goal in 3-200 characters, e.g. Learn Java from basic to advanced."
        )
    return goal


# --- building ------------------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")[:40]


def _units_for_level(units: list[dict[str, Any]], level: str) -> list[dict[str, Any]]:
    basics = [u for u in units if u["stage"] == "Basics"]
    rest = [u for u in units if u["stage"] != "Basics"]
    if level == "beginner" or not basics:
        return units
    merged = {
        "title": "Quick review of the basics" if level == "some" else "Basics check",
        "stage": "Basics",
        "topics": [t for u in basics for t in u["topics"]]
        if level == "some"
        else [u["title"] for u in basics],
        "practice": list(dict.fromkeys(p for u in basics for p in u["practice"])),
        "exercise": (
            "Redo one exercise from each basics topic quickly to make sure nothing is missing."
            if level == "some"
            else "Skip what you know: if the practice below goes well, move straight on."
        ),
        "optional_study": level == "experienced",
    }
    return [merged, *rest]


def _group(units: list[dict[str, Any]], pace: str) -> list[list[dict[str, Any]]]:
    """One unit per week, or two from the same stage per week at the fast pace."""
    if pace != "fast":
        return [[u] for u in units]
    weeks: list[list[dict[str, Any]]] = []
    for u in units:
        last = weeks[-1] if weeks else None
        if last and len(last) == 1 and last[0]["stage"] == u["stage"] and u["stage"] != "Project":
            last.append(u)
        else:
            weeks.append([u])
    return weeks


def build_weeks(units: Sequence[Mapping[str, Any]], level: str, pace: str) -> list[dict[str, Any]]:
    if level not in LEVELS or pace not in PACES:
        raise RoadmapError("Choose a level and a pace.")
    grouped = _group(_units_for_level([dict(u) for u in units], level), pace)
    weeks: list[dict[str, Any]] = []
    for n, group in enumerate(grouped, start=1):
        stage = group[0]["stage"]
        tasks: list[dict[str, Any]] = []
        topics = [t for u in group for t in u["topics"]]
        tasks.append(
            {
                "id": f"w{n}-study",
                "kind": "study",
                "text": "Study: " + "; ".join(topics),
                "optional": any(u.get("optional_study") for u in group),
            }
        )
        practice = list(dict.fromkeys(p for u in group for p in u.get("practice", [])))
        if practice:
            tasks.append(
                {
                    "id": f"w{n}-practice",
                    "kind": "practice",
                    "text": f"Practise {PRACTICE_TARGET} questions on "
                    + ", ".join(practice)
                    + f" and get {round(PRACTICE_PASS * 100)}% or more",
                    "topics": practice,
                    "target": PRACTICE_TARGET,
                    "pass": PRACTICE_PASS,
                }
            )
        for i, u in enumerate(group):
            if u.get("project"):
                tasks.append({"id": f"w{n}-project{i}", "kind": "project", "text": u["project"]})
            elif u.get("exercise"):
                tasks.append({"id": f"w{n}-code{i}", "kind": "exercise", "text": u["exercise"]})
        weeks.append(
            {
                "n": n,
                "title": " + ".join(u["title"] for u in group),
                "stage": stage,
                "topics": topics,
                "tasks": tasks,
            }
        )
    # a checkpoint at the end of each stage that has bank topics
    for stage in STAGES:
        in_stage = [w for w in weeks if w["stage"] == stage]
        topics = list(
            dict.fromkeys(
                t
                for w in in_stage
                for task in w["tasks"]
                if task["kind"] == "practice"
                for t in task["topics"]
            )
        )
        if in_stage and topics and len(in_stage) > 1:
            in_stage[-1]["tasks"].append(
                {
                    "id": f"checkpoint-{_slug(stage)}",
                    "kind": "checkpoint",
                    "text": f"{stage} checkpoint: answer {CHECKPOINT_TARGET} questions across "
                    f"this stage's topics and score {round(CHECKPOINT_PASS * 100)}% or more",
                    "topics": topics,
                    "target": CHECKPOINT_TARGET,
                    "pass": CHECKPOINT_PASS,
                }
            )
    for w in weeks:
        for task in w["tasks"]:
            task.setdefault("optional", False)
            task.update(done=False, done_at=None, auto=False)
    return weeks


def from_template(subject: str, level: str, pace: str) -> list[dict[str, Any]]:
    return build_weeks(templates()[subject]["units"], level, pace)


# --- roadmaps written by the AI model (subjects without a template) ------------------------------


class DraftWeek(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    stage: str
    topics: list[str] = Field(min_length=1, max_length=8)
    exercise: str = Field(min_length=5, max_length=400)


class Draft(BaseModel):
    weeks: list[DraftWeek] = Field(min_length=4, max_length=16)


DRAFT_SYSTEM = (
    'You plan self-study. Reply with JSON only: {"weeks": [{"title", "stage", "topics", '
    '"exercise"}]}. Make 8 to 12 weeks that go from basics to advanced and end with a project '
    "week. stage is one of Basics, Intermediate, Advanced, Project. topics are 2-5 short topic "
    "names. exercise is one concrete hands-on task. Use correct, standard topics only."
)


def from_draft(draft: Draft, level: str, pace: str) -> list[dict[str, Any]]:
    units = []
    for w in draft.weeks:
        stage = w.stage if w.stage in STAGES else "Intermediate"
        unit: dict[str, Any] = {
            "title": " ".join(w.title.split())[:120],
            "stage": stage,
            "topics": [" ".join(t.split())[:80] for t in w.topics if t.strip()][:6],
            "practice": [],
        }
        unit["project" if stage == "Project" else "exercise"] = " ".join(w.exercise.split())[:400]
        units.append(unit)
    return build_weeks(units, level, pace)


# --- progress ------------------------------------------------------------------------------------


def _since(results: Iterable[Mapping[str, Any]], start: datetime) -> list[Mapping[str, Any]]:
    out = []
    for r in results:
        at = r.get("at")
        if isinstance(at, datetime):
            at = at if at.tzinfo else at.replace(tzinfo=UTC)
            if at >= start:
                out.append(r)
    return out


def _topic_counts(results: Iterable[Mapping[str, Any]], topics: Iterable[str]) -> tuple[int, int]:
    wanted = set(topics)
    rows = [r for r in results if r["topic"] in wanted]
    return len(rows), sum(bool(r["correct"]) for r in rows)


def refresh(roadmap: m.Roadmap, results: Sequence[Mapping[str, Any]], now: datetime) -> bool:
    """Ticks practice and checkpoint tasks reached in My Learning since the roadmap was made, and
    records each task's progress. Returns whether anything was newly completed."""
    since = _since(results, roadmap.created_at)
    changed = False
    for w in roadmap.weeks:
        for task in w["tasks"]:
            if task["kind"] not in ("practice", "checkpoint", "review"):
                continue
            answered, right = _topic_counts(since, task.get("topics", []))
            task["answered"], task["right"] = answered, right
            reached = answered >= task.get(
                "target", PRACTICE_TARGET
            ) and right / answered >= task.get("pass", PRACTICE_PASS)
            if reached and not task["done"]:
                task.update(done=True, done_at=now, auto=True)
                changed = True
    return changed


def week_done(week: Mapping[str, Any]) -> bool:
    return all(t["done"] or t.get("optional") for t in week["tasks"])


def current_week(roadmap: m.Roadmap) -> int:
    """The first week with required work left (or the last week when all is done)."""
    for w in roadmap.weeks:
        if not week_done(w):
            return int(w["n"])
    return int(roadmap.weeks[-1]["n"]) if roadmap.weeks else 1


def summary(roadmap: m.Roadmap, now: datetime) -> dict[str, Any]:
    required = [t for w in roadmap.weeks for t in w["tasks"] if not t.get("optional")]
    done = sum(1 for t in required if t["done"])
    weeks_done = sum(1 for w in roadmap.weeks if week_done(w))
    cur = current_week(roadmap)
    planned = max(1, min(len(roadmap.weeks), (now - roadmap.start_date).days // 7 + 1))
    return {
        "tasks_done": done,
        "tasks_total": len(required),
        "percent": round(done / len(required), 3) if required else 0.0,
        "weeks_done": weeks_done,
        "weeks_total": len(roadmap.weeks),
        "current_week": cur,
        "planned_week": planned,
        "behind": max(0, planned - cur),
        "finish_by": roadmap.start_date + timedelta(weeks=len(roadmap.weeks)),
    }


# --- adapting ------------------------------------------------------------------------------------


def _log(roadmap: m.Roadmap, key: str, text: str, now: datetime) -> bool:
    if any(a["key"] == key for a in roadmap.adaptations):
        return False
    roadmap.adaptations = [*roadmap.adaptations, {"key": key, "at": now, "text": text}]
    return True


def adapt(roadmap: m.Roadmap, results: Sequence[Mapping[str, Any]], now: datetime) -> list[str]:
    """Adjusts the plan to the student's results; returns the new changes' explanations.
    Idempotent: each change is made once (keyed in ``adaptations``)."""
    notes: list[str] = []
    stats = pr.topic_stats(results)
    cur_n = current_week(roadmap)
    by_n = {w["n"]: w for w in roadmap.weeks}
    cur = by_n.get(cur_n)

    # 1. Topics of the weeks so far that the student keeps missing get a review task now.
    if cur is not None:
        seen_topics = list(
            dict.fromkeys(
                t
                for w in roadmap.weeks
                if w["n"] <= cur_n
                for task in w["tasks"]
                if task["kind"] == "practice"
                for t in task["topics"]
            )
        )
        for topic in seen_topics:
            st = stats.get(topic)
            if (
                st is None
                or st.answered < pr.MIN_EVIDENCE
                or st.right / st.answered >= REVIEW_BELOW
            ):
                continue
            key = f"review:{_slug(topic)}"
            text = (
                f"Added a review of {topic} to week {cur_n}: you got {st.right} of {st.answered} "
                f"right ({round(st.right / st.answered * 100)}%)."
            )
            if _log(roadmap, key, text, now) and cur is not None:
                cur["tasks"].append(
                    {
                        "id": key,
                        "kind": "review",
                        "text": f"Review {topic}: practise until you reach "
                        f"{round(PRACTICE_PASS * 100)}% over {PRACTICE_TARGET} answers",
                        "topics": [topic],
                        "target": PRACTICE_TARGET,
                        "pass": PRACTICE_PASS,
                        "optional": False,
                        "done": False,
                        "done_at": None,
                        "auto": False,
                        "added": True,
                    }
                )
                notes.append(text)

    # 2. Future weeks whose topics the student already masters become optional.
    for w in roadmap.weeks:
        if w["n"] <= cur_n or w["stage"] == "Project":
            continue
        practice = [t for task in w["tasks"] if task["kind"] == "practice" for t in task["topics"]]
        if not practice:
            continue
        strong = [stats.get(t) for t in practice]
        if all(
            s is not None and s.answered >= SKIP_EVIDENCE and s.mastery >= SKIP_FROM for s in strong
        ):
            key = f"skip:w{w['n']}"
            text = (
                f"Week {w['n']} ({w['title']}) is now optional: you already score well on "
                + ", ".join(practice)
                + "."
            )
            if _log(roadmap, key, text, now):
                for task in w["tasks"]:
                    if task["kind"] in ("study", "practice", "exercise"):
                        task["optional"] = True
                notes.append(text)

    # 3. Falling behind: move the dates so the current week is this week.
    planned = (now - roadmap.start_date).days // 7 + 1
    if planned - cur_n >= 2:
        key = f"dates:{now.date().isoformat()}"
        text = (
            f"You were {planned - cur_n} weeks behind the planned dates, so the dates moved: "
            f"week {cur_n} starts now."
        )
        if _log(roadmap, key, text, now):
            roadmap.start_date = now - timedelta(weeks=cur_n - 1)
            notes.append(text)
    return notes
