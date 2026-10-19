"""Roadmaps: goals map to subjects, weeks go from basics to a project, tasks tick themselves
from practice results, and the plan adapts (D44)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from mentora import practice as pr
from mentora import roadmaps as rm
from mentora.db import models as m

NOW = datetime(2026, 3, 1, tzinfo=UTC)


def results(topic: str, right: int, wrong: int, at: datetime = NOW) -> list[dict[str, Any]]:
    return [
        {"id": i, "topic": topic, "correct": i < right, "choice": 0, "at": at}
        for i in range(right + wrong)
    ]


def roadmap(subject: str = "Java", level: str = "beginner", pace: str = "steady") -> m.Roadmap:
    r = m.Roadmap(
        student_id="s",
        goal="g",
        subject=subject,
        weeks=rm.from_template(subject, level, pace),
        level=level,
        pace=pace,
    )
    r.created_at = r.start_date = NOW - timedelta(days=1)
    return r


@pytest.mark.parametrize(
    ("goal", "subject"),
    [
        ("How to learn Java from Basic to Advanced", "Java"),
        ("master DSA for interviews", "Data Structures"),
        ("become a full stack web developer", "Web Development"),
        ("SQL and databases", "DBMS"),
        ("neural networks and deep learning", "Machine Learning"),
        ("computer networking basics", "Computer Networks"),
        ("Learn to cook pasta", None),
        ("javascript", "Web Development"),
    ],
)
def test_goals_find_their_subject(goal: str, subject: str | None) -> None:
    assert rm.match_subject(goal) == subject


def test_templates_use_real_bank_topics_and_end_with_a_project() -> None:
    banks = {f["subject"]: {q[0] for q in f["questions"]} for f in pr.starter_files()}
    assert set(rm.templates()) == set(banks)
    for subject, spec in rm.templates().items():
        stages = [u["stage"] for u in spec["units"]]
        assert stages[0] == "Basics" and stages[-1] == "Project", subject
        assert stages == sorted(stages, key=rm.STAGES.index), subject  # basics -> advanced
        used = {p for u in spec["units"] for p in u["practice"]}
        assert used <= banks[subject], (subject, used - banks[subject])


def test_levels_and_pace_shape_the_weeks() -> None:
    full = rm.from_template("Java", "beginner", "steady")
    assert len(full) == len(rm.templates()["Java"]["units"])
    assert full[0]["title"] == "Java fundamentals and setup"
    kinds = {t["kind"] for w in full for t in w["tasks"]}
    assert {"study", "practice", "exercise", "project", "checkpoint"} <= kinds
    some = rm.from_template("Java", "some", "steady")
    assert some[0]["title"] == "Quick review of the basics" and len(some) == len(full) - 2
    expert = rm.from_template("Java", "experienced", "steady")
    assert expert[0]["tasks"][0]["optional"] is True  # study the basics only if needed
    fast = rm.from_template("Java", "beginner", "fast")
    assert len(fast) < len(full) and fast[-1]["stage"] == "Project"
    with pytest.raises(rm.RoadmapError):
        rm.from_template("Java", "guru", "steady")


def test_practice_tasks_tick_themselves() -> None:
    r = roadmap()
    week1 = r.weeks[0]
    practice = next(t for t in week1["tasks"] if t["kind"] == "practice")
    before = results("Basics and the JVM", 9, 1, at=NOW - timedelta(days=5))  # before the roadmap
    assert rm.refresh(r, before, NOW) is False and not practice["done"]
    assert rm.refresh(r, results("Basics and the JVM", 4, 2), NOW) is False  # only 6 answers
    assert practice["answered"] == 6
    assert rm.refresh(
        r, results("Data types and operators", 7, 3) + results("Basics and the JVM", 4, 2), NOW
    )
    assert practice["done"] and practice["auto"]
    for t in week1["tasks"]:
        t["done"] = True
    assert rm.current_week(r) == 2
    s = rm.summary(r, NOW)
    assert s["weeks_done"] == 1 and 0 < s["percent"] < 1


def test_adapt_adds_reviews_skips_mastered_weeks_and_moves_dates() -> None:
    r = roadmap()
    history = (
        results("Basics and the JVM", 1, 4)
        + results("Exceptions", 9, 1)
        + [{"id": 100 + i, "topic": "Exceptions", "correct": True, "at": NOW} for i in range(5)]
    )
    notes = rm.adapt(r, history, NOW)
    week1 = r.weeks[0]
    review = [t for t in week1["tasks"] if t["kind"] == "review"]
    assert len(review) == 1 and review[0]["topics"] == ["Basics and the JVM"]
    exceptions_week = next(w for w in r.weeks if "Exception" in w["title"])
    assert all(t["optional"] for t in exceptions_week["tasks"] if t["kind"] != "checkpoint")
    assert len(notes) == 2 and "Basics and the JVM" in notes[0]
    assert rm.adapt(r, history, NOW) == []  # each change happens once
    assert len([t for t in week1["tasks"] if t["kind"] == "review"]) == 1

    later = NOW + timedelta(weeks=4)
    notes = rm.adapt(r, [], later)
    assert any("behind" in n for n in notes)
    assert rm.summary(r, later)["behind"] == 0


def test_ai_drafts_are_cleaned() -> None:
    draft = rm.Draft(
        weeks=[
            rm.DraftWeek(
                title="Knife skills",
                stage="Basics",
                topics=["Grip", "Cuts"],
                exercise="Dice an onion",
            ),
            rm.DraftWeek(
                title="Sauces", stage="Weird", topics=["Roux"], exercise="Make a bechamel"
            ),
            rm.DraftWeek(
                title="Pasta", stage="Intermediate", topics=["Dough"], exercise="Make fresh pasta"
            ),
            rm.DraftWeek(
                title="Dinner party", stage="Project", topics=["Menu"], exercise="Cook for four"
            ),
        ]
    )
    weeks = rm.from_draft(draft, "beginner", "steady")
    assert [w["stage"] for w in weeks] == ["Basics", "Intermediate", "Intermediate", "Project"]
    assert weeks[-1]["tasks"][-1]["kind"] == "project"
    assert not any(t["kind"] == "practice" for w in weeks for t in w["tasks"])
