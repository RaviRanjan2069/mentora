"""Question banks and adaptive practice (D43).

Every subject has a bank of multiple-choice questions: starter questions shipped with Mentora
(``mentora/subjects_data/*.json``) plus questions its teachers add. A student practises in rounds
of 10. Each round leans towards the topics the student gets wrong most often:

* topic mastery is estimated as (right + 1) / (answered + 2), so one lucky or unlucky answer does
  not decide anything and an unseen topic starts at 50%;
* round slots go to topics in proportion to (1 - mastery), plus a little for every topic so
  strong topics still come back now and then; each extra slot for the same topic in one round
  counts for less, so a round is never all one topic;
* inside a topic, questions the student got wrong come back first (review), then questions
  never seen, then the ones answered right least often; the previous round's questions are
  avoided when there are others, so a mistake returns a round later, not straight away.
"""

from __future__ import annotations

import hashlib
import json
import random
import threading
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from importlib import resources
from typing import Any

from mentora import subjects as sub
from mentora.db import Store
from mentora.db import models as m

ROUND_SIZE = 10
WEAK, STRONG = 0.6, 0.75  # mastery below / at or above (with at least MIN_EVIDENCE answers)
MIN_EVIDENCE = 3
EXPLORE = 0.12  # weight every topic keeps
REASONS = {
    "weak": "A topic you often miss",
    "review": "You got this one wrong before",
    "new": "A topic you have not tried yet",
    "mixed": "Keeps your other topics fresh",
}


class PracticeError(ValueError):
    """A request that cannot be done; the message is safe to show."""


# --- starter questions -------------------------------------------------------------------------


def seed_key(subject_key: str, text: str) -> str:
    digest = hashlib.sha1(" ".join(text.split()).casefold().encode()).hexdigest()[:12]
    return f"{subject_key}:{digest}"


def starter_files() -> list[dict[str, Any]]:
    """The shipped question banks: [{subject, questions: [[topic, text, options, answer,
    explanation, difficulty?], ...]}]."""
    out = []
    for entry in sorted(resources.files("mentora.subjects_data").iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".json"):
            out.append(json.loads(entry.read_text(encoding="utf-8")))
    return out


_SEEDED: set[int] = set()
_SEED_LOCK = threading.Lock()


def ensure_starter_questions(db: Store) -> int:
    """Adds starter questions that are missing (once per database per process). Returns how
    many were added. Questions a teacher edited or hid are left as they are."""
    marker = id(db.db)
    if marker in _SEEDED:
        return 0
    with _SEED_LOCK:  # two first requests at once must not both add the questions
        if marker in _SEEDED:
            return 0
        added = _seed(db)
        _SEEDED.add(marker)
        return added


def _seed(db: Store) -> int:
    sub.ensure_default_subjects(db)
    added = 0
    for bank in starter_files():
        subject = sub.find_or_add_subject(db, bank["subject"], account_id="")
        if subject.created_by == "":
            subject.created_by = None
        have = {
            key
            for (key,) in db.values(m.BankQuestion, ["seed_key"], {"subject_id": subject.id})
            if key
        }
        for row in bank["questions"]:
            topic, text, options, answer, explanation = row[:5]
            key = seed_key(subject.key, text)
            if key in have:
                continue
            have.add(key)
            db.add(
                m.BankQuestion(
                    subject_id=subject.id,
                    topic=topic,
                    text=text,
                    options=list(options),
                    answer=int(answer),
                    explanation=explanation,
                    difficulty=int(row[5]) if len(row) > 5 else 2,
                    seed_key=key,
                )
            )
            added += 1
    db.commit()
    return added


# --- checking teachers' questions -------------------------------------------------------------


def clean_question(raw: Mapping[str, Any]) -> dict[str, Any]:
    topic = " ".join(str(raw.get("topic") or "").split())
    text = " ".join(str(raw.get("text") or "").split())
    options = [" ".join(str(o).split()) for o in raw.get("options") or []]
    options = [o for o in options if o]
    explanation = str(raw.get("explanation") or "").strip()
    if not 1 <= len(topic) <= 60:
        raise PracticeError("Give the question a topic (up to 60 characters).")
    if not 5 <= len(text) <= 2000:
        raise PracticeError("Write the question (at least 5 characters).")
    if not 2 <= len(options) <= 6 or any(len(o) > 300 for o in options):
        raise PracticeError("Give 2-6 options of up to 300 characters.")
    if len({o.casefold() for o in options}) != len(options):
        raise PracticeError("Two options are the same.")
    try:
        answer = int(raw.get("answer", -1))
    except (TypeError, ValueError) as exc:
        raise PracticeError("Mark the right option.") from exc
    if not 0 <= answer < len(options):
        raise PracticeError("Mark the right option.")
    try:
        difficulty = int(raw.get("difficulty") or 2)
    except (TypeError, ValueError):
        difficulty = 2
    if len(explanation) > 2000:
        raise PracticeError("Keep the explanation under 2000 characters.")
    return {
        "topic": topic,
        "text": text,
        "options": options,
        "answer": answer,
        "explanation": explanation,
        "difficulty": min(3, max(1, difficulty)),
    }


CSV_COLUMNS = ("topic", "question", "option_a", "option_b", "option_c", "option_d", "answer")


def parse_csv_rows(rows: Sequence[Mapping[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Rows from a CSV upload -> (clean questions, problems as "Row n: ...")."""
    good, problems = [], []
    for n, row in enumerate(rows, start=2):  # row 1 is the header
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        letters = [
            k for k in ("option_a", "option_b", "option_c", "option_d", "option_e", "option_f")
        ]
        options = [r[k] for k in letters if r.get(k)]
        letter = r.get("answer", "").upper()
        if len(letter) == 1 and "A" <= letter <= "F":
            answer = ord(letter) - ord("A")
        else:  # the right option's text
            answer = next(
                (i for i, o in enumerate(options) if o.casefold() == letter.casefold()), -1
            )
        try:
            good.append(
                clean_question(
                    {
                        "topic": r.get("topic"),
                        "text": r.get("question"),
                        "options": options,
                        "answer": answer,
                        "explanation": r.get("explanation", ""),
                        "difficulty": r.get("difficulty") or 2,
                    }
                )
            )
        except PracticeError as exc:
            problems.append(f"Row {n}: {exc}")
    return good, problems


# --- statistics ---------------------------------------------------------------------------------


@dataclass
class TopicStat:
    topic: str
    answered: int = 0
    right: int = 0

    @property
    def mastery(self) -> float:
        return (self.right + 1) / (self.answered + 2)

    @property
    def accuracy(self) -> float | None:
        return self.right / self.answered if self.answered else None


def results_of(rounds: Iterable[m.PracticeRound]) -> list[dict[str, Any]]:
    return [r for rnd in rounds for r in rnd.results]


def topic_stats(
    results: Iterable[Mapping[str, Any]], topics: Iterable[str] = ()
) -> dict[str, TopicStat]:
    stats = {t: TopicStat(t) for t in topics}
    for r in results:
        s = stats.setdefault(r["topic"], TopicStat(r["topic"]))
        s.answered += 1
        s.right += bool(r["correct"])
    return stats


def label(stat: TopicStat) -> str:
    if stat.answered < MIN_EVIDENCE:
        return "new" if stat.answered == 0 else "learning"
    if stat.mastery < WEAK:
        return "weak"
    if stat.mastery >= STRONG:
        return "strong"
    return "learning"


# --- choosing a round ---------------------------------------------------------------------------


@dataclass
class Pick:
    question: m.BankQuestion
    reason: str


@dataclass
class _Seen:
    times: int = 0
    last_correct: bool = True
    last_at: float = 0.0


@dataclass
class RoundPlan:
    picks: list[Pick] = field(default_factory=list)
    focus: list[str] = field(default_factory=list)


def plan_round(
    questions: Sequence[m.BankQuestion],
    results: Sequence[Mapping[str, Any]],
    *,
    size: int = ROUND_SIZE,
    last_round: Iterable[int] = (),
    rng: random.Random | None = None,
) -> RoundPlan:
    """The questions for the next round, each with why it was chosen."""
    rng = rng or random.Random()
    pool = [q for q in questions if not q.hidden]
    if not pool:
        raise PracticeError("This subject has no questions yet.")
    by_topic: dict[str, list[m.BankQuestion]] = defaultdict(list)
    for q in pool:
        by_topic[q.topic].append(q)
    stats = topic_stats(results, by_topic)
    seen: dict[int, _Seen] = defaultdict(_Seen)
    for r in results:
        s = seen[r["id"]]
        s.times += 1
        at = r.get("at")
        stamp = at.timestamp() if isinstance(at, datetime) else 0.0
        if stamp >= s.last_at:
            s.last_at, s.last_correct = stamp, bool(r["correct"])
    recent = set(last_round)

    def weight(topic: str, given: int) -> float:
        st = stats[topic]
        base = (0.55 if st.answered == 0 else 1 - st.mastery) + EXPLORE
        return float(base / (1 + given) ** 1.5)  # each extra slot in this round counts for less

    def question_score(q: m.BankQuestion) -> float:
        s = seen.get(q.id)
        if s is None or s.times == 0:
            score = 3.0
        elif not s.last_correct:
            score = 3.5
        else:
            score = 1.0 / (1 + s.times)
        if q.id in recent:
            score -= 2.0
        return score + rng.random() * 0.01

    chosen: list[Pick] = []
    used: set[int] = set()
    given: dict[str, int] = defaultdict(int)
    for _ in range(min(size, len(pool))):
        open_topics = [t for t, qs in by_topic.items() if any(q.id not in used for q in qs)]
        weights = [weight(t, given[t]) for t in open_topics]
        topic = rng.choices(open_topics, weights=weights, k=1)[0]
        q = max((q for q in by_topic[topic] if q.id not in used), key=question_score)
        used.add(q.id)
        given[topic] += 1
        st = stats[topic]
        prior = seen.get(q.id)
        if prior is not None and prior.times and not prior.last_correct:
            reason = "review"
        elif st.answered == 0:
            reason = "new"
        elif st.answered >= MIN_EVIDENCE and st.mastery < WEAK:
            reason = "weak"
        else:
            reason = "mixed"
        chosen.append(Pick(q, reason))
    rng.shuffle(chosen)
    weak = sorted(
        (s for s in stats.values() if s.answered >= MIN_EVIDENCE and s.mastery < WEAK),
        key=lambda s: s.mastery,
    )
    return RoundPlan(chosen, [s.topic for s in weak[:3]])


# --- progress -------------------------------------------------------------------------------------


def _pct(right: int, answered: int) -> float | None:
    return round(right / answered, 3) if answered else None


def subject_progress(
    rounds: Sequence[m.PracticeRound], topics: Iterable[str] = ()
) -> dict[str, Any]:
    """Topic table, strengths, weaknesses and the score of each finished round."""
    results = results_of(rounds)
    stats = topic_stats(results, topics)
    rows = sorted(
        (
            {
                "topic": s.topic,
                "answered": s.answered,
                "right": s.right,
                "accuracy": _pct(s.right, s.answered),
                "mastery": round(s.mastery, 3),
                "label": label(s),
            }
            for s in stats.values()
        ),
        key=lambda r: (r["answered"] == 0, r["mastery"], r["topic"]),
    )
    finished = [r for r in rounds if r.finished_at is not None]
    right = sum(bool(r["correct"]) for r in results)
    return {
        "answered": len(results),
        "right": right,
        "accuracy": _pct(right, len(results)),
        "rounds": len(finished),
        "last_practiced": max((r.finished_at for r in finished if r.finished_at), default=None),
        "topics": rows,
        "strengths": [r["topic"] for r in rows if r["label"] == "strong"][::-1],
        "weaknesses": [r["topic"] for r in rows if r["label"] == "weak"],
        "trend": [
            {
                "round_id": r.id,
                "at": r.finished_at,
                "score": r.score,
                "total": r.total,
                "accuracy": _pct(r.score, r.total),
            }
            for r in sorted(finished, key=lambda r: r.finished_at or r.started_at)
        ],
    }


def improvement(trend: Sequence[Mapping[str, Any]]) -> float | None:
    """Average of the last three rounds minus the first three (None with fewer than 4 rounds)."""
    acc = [float(t["accuracy"]) for t in trend if t["accuracy"] is not None]
    if len(acc) < 4:
        return None
    k = min(3, len(acc) // 2)
    return round(sum(acc[-k:]) / k - sum(acc[:k]) / k, 3)


def question_stats(rounds: Iterable[m.PracticeRound]) -> dict[int, tuple[int, int]]:
    """question id -> (answered, right) over all students (for teachers spotting bad questions)."""
    out: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for r in results_of(rounds):
        out[r["id"]][0] += 1
        out[r["id"]][1] += bool(r["correct"])
    return {k: (v[0], v[1]) for k, v in out.items()}
