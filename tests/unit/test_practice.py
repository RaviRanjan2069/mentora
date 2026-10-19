"""Adaptive practice: rounds lean towards weak topics, review mistakes, and starter banks load."""

from __future__ import annotations

import random
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from mentora import practice as pr
from mentora.db import models as m

TOPICS = ["Loops", "Strings", "Classes", "Files"]


def bank() -> list[m.BankQuestion]:
    out = []
    for t_i, topic in enumerate(TOPICS):
        for n in range(10):
            q = m.BankQuestion(
                subject_id=1,
                topic=topic,
                text=f"{topic} q{n}",
                options=["a", "b", "c", "d"],
                answer=0,
            )
            q.id = t_i * 100 + n
            out.append(q)
    return out


def result(qid: int, topic: str, correct: bool, minutes: int = 0) -> dict[str, Any]:
    return {
        "id": qid,
        "topic": topic,
        "correct": correct,
        "choice": 0,
        "at": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes),
    }


def test_first_round_spreads_over_topics() -> None:
    plan = pr.plan_round(bank(), [], rng=random.Random(1))
    assert len(plan.picks) == 10 and len({p.question.id for p in plan.picks}) == 10
    topics = Counter(p.question.topic for p in plan.picks)
    assert len(topics) == 4 and max(topics.values()) <= 4
    assert all(p.reason == "new" for p in plan.picks)
    assert plan.focus == []


def test_rounds_lean_towards_weak_topics() -> None:
    qs = bank()
    history = []
    for n in range(6):  # Loops: wrong every time; others: right every time
        history.append(result(n, "Loops", False, n))
        history.append(result(100 + n, "Strings", True, n))
        history.append(result(200 + n, "Classes", True, n))
        history.append(result(300 + n, "Files", True, n))
    counts: Counter[str] = Counter()
    for seed in range(40):
        plan = pr.plan_round(qs, history, rng=random.Random(seed))
        counts.update(p.question.topic for p in plan.picks)
        assert plan.focus == ["Loops"]
    assert counts["Loops"] > 2 * counts["Strings"]  # weak topic gets the most questions
    assert counts["Strings"] > 0  # strong topics still come back now and then


def test_mistakes_come_back_for_review_and_last_round_is_avoided() -> None:
    qs = bank()
    history = [result(5, "Loops", False), result(6, "Loops", True), result(7, "Loops", True)]
    picks = [
        p for seed in range(20) for p in pr.plan_round(qs, history, rng=random.Random(seed)).picks
    ]
    assert any(p.question.id == 5 and p.reason == "review" for p in picks)
    last = [p.question.id for p in pr.plan_round(qs, [], rng=random.Random(3)).picks]
    nxt = pr.plan_round(qs, [], last_round=last, rng=random.Random(4))
    assert not set(last) & {p.question.id for p in nxt.picks}


def test_hidden_questions_are_never_asked() -> None:
    qs = bank()
    for q in qs:
        q.hidden = q.topic != "Files"
    plan = pr.plan_round(qs, [], rng=random.Random(0))
    assert {p.question.topic for p in plan.picks} == {"Files"}
    for q in qs:
        q.hidden = True
    with pytest.raises(pr.PracticeError):
        pr.plan_round(qs, [])


def test_progress_labels_and_improvement() -> None:
    rnds = []
    for i, score in enumerate([2, 4, 5, 8, 9]):
        r = m.PracticeRound(student_id="s", subject_id=1, score=score, total=10)
        r.id = i + 1
        r.finished_at = datetime(2026, 1, 1 + i, tzinfo=UTC)
        r.results = [result(n, "Loops", n < score) for n in range(10)]
        rnds.append(r)
    prog = pr.subject_progress(rnds, ["Loops", "Files"])
    assert prog["answered"] == 50 and prog["rounds"] == 5
    assert [t["topic"] for t in prog["topics"]] == ["Loops", "Files"]  # unseen topics last
    assert prog["topics"][1]["label"] == "new"
    assert [t["accuracy"] for t in prog["trend"]] == [0.2, 0.4, 0.5, 0.8, 0.9]
    assert pr.improvement(prog["trend"]) == pytest.approx(0.85 - 0.3, abs=1e-3)


def test_csv_rows_and_starter_banks() -> None:
    good, problems = pr.parse_csv_rows(
        [
            {
                "topic": "Loops",
                "question": "What does break do?",
                "option_a": "Exit",
                "option_b": "Skip",
                "answer": "A",
                "explanation": "It leaves the loop.",
            },
            {
                "topic": "Loops",
                "question": "Pick the loop",
                "option_a": "for",
                "option_b": "if",
                "answer": "for",
            },
            {
                "topic": "",
                "question": "No topic here",
                "option_a": "x",
                "option_b": "y",
                "answer": "A",
            },
            {
                "topic": "T",
                "question": "Bad answer letter",
                "option_a": "x",
                "option_b": "y",
                "answer": "D",
            },
        ]
    )
    assert [g["answer"] for g in good] == [0, 0]
    assert [p.split(":")[0] for p in problems] == ["Row 4", "Row 5"]

    files = pr.starter_files()
    assert len(files) == 8
    for f in files:
        assert len(f["questions"]) >= 100, f["subject"]
        assert len({q[0] for q in f["questions"]}) >= 8
