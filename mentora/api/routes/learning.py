"""My Learning: adaptive practice per subject and progress analytics; teachers' question banks
(D43). Rules in mentora.practice."""

from __future__ import annotations

import csv
import io
import random
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field

from mentora import practice as pr
from mentora.api.deps import User, db_session, require_learner, require_teacher
from mentora.api.routes.accounts import _account
from mentora.db import Store
from mentora.db import models as m
from mentora.practice import PracticeError

router = APIRouter(prefix="/api", tags=["learning"])

Db = Annotated[Store, Depends(db_session)]
Learner = Annotated[User, Depends(require_learner)]
Teacher = Annotated[User, Depends(require_teacher)]


def _bad(exc: PracticeError) -> HTTPException:
    return HTTPException(422, str(exc))


def _subject(db: Store, subject_id: int) -> m.Subject:
    subject = db.get(m.Subject, subject_id)
    if subject is None:
        raise HTTPException(404, "No such subject.")
    return subject


def _visible(db: Store, subject_id: int) -> list[m.BankQuestion]:
    return db.find(m.BankQuestion, {"subject_id": subject_id, "hidden": False}, sort=[("id", 1)])


def _rounds(db: Store, student_id: str, subject_id: int | None = None) -> list[m.PracticeRound]:
    query: dict[str, Any] = {"student_id": student_id}
    if subject_id is not None:
        query["subject_id"] = subject_id
    return db.find(m.PracticeRound, query, sort=[("started_at", 1), ("id", 1)])


# --- students: subjects and progress -----------------------------------------------------------


class SubjectCard(BaseModel):
    id: int
    name: str
    questions: int
    topics: int
    answered: int
    accuracy: float | None
    rounds: int
    last_practiced: datetime | None
    weakest: str | None
    strongest: str | None
    open_round: int | None


@router.get("/learning/subjects")
def learning_subjects(user: Learner, db: Db) -> list[SubjectCard]:
    """Every subject with questions, with the student's numbers."""
    pr.ensure_starter_questions(db)
    account = _account(db, user)
    counts: dict[int, list[str]] = {}
    for sid, topic in db.values(m.BankQuestion, ["subject_id", "topic"], {"hidden": False}):
        counts.setdefault(sid, []).append(topic)
    rounds_by: dict[int, list[m.PracticeRound]] = {}
    for r in _rounds(db, account.id):
        rounds_by.setdefault(r.subject_id, []).append(r)
    out = []
    for s in db.find(m.Subject, {"id": {"$in": list(counts)}}, sort=[("name", 1)]):
        rounds = rounds_by.get(s.id, [])
        prog = pr.subject_progress(rounds, set(counts[s.id]))
        seen = [t for t in prog["topics"] if t["answered"]]
        open_ = next((r for r in reversed(rounds) if r.finished_at is None), None)
        out.append(
            SubjectCard(
                id=s.id,
                name=s.name,
                questions=len(counts[s.id]),
                topics=len(set(counts[s.id])),
                answered=prog["answered"],
                accuracy=prog["accuracy"],
                rounds=prog["rounds"],
                last_practiced=prog["last_practiced"],
                weakest=seen[0]["topic"] if seen else None,
                strongest=max(seen, key=lambda t: t["mastery"])["topic"] if seen else None,
                open_round=open_.id if open_ else None,
            )
        )
    return out


@router.get("/learning/progress")
def overall_progress(user: Learner, db: Db) -> dict[str, Any]:
    """Every subject's numbers plus all rounds in time order (for the dashboard graphs)."""
    pr.ensure_starter_questions(db)
    account = _account(db, user)
    rounds = _rounds(db, account.id)
    subjects = {s.id: s.name for s in db.find(m.Subject)}
    by_subject: dict[int, list[m.PracticeRound]] = {}
    for r in rounds:
        by_subject.setdefault(r.subject_id, []).append(r)
    per_subject = []
    for sid, rs in by_subject.items():
        prog = pr.subject_progress(rs)
        per_subject.append(
            {
                "id": sid,
                "name": subjects.get(sid, "?"),
                "answered": prog["answered"],
                "accuracy": prog["accuracy"],
                "rounds": prog["rounds"],
                "strengths": prog["strengths"],
                "weaknesses": prog["weaknesses"],
                "improvement": pr.improvement(prog["trend"]),
            }
        )
    per_subject.sort(key=lambda s: s["name"])
    results = pr.results_of(rounds)
    right = sum(bool(r["correct"]) for r in results)
    finished = [r for r in rounds if r.finished_at is not None]
    return {
        "answered": len(results),
        "accuracy": round(right / len(results), 3) if results else None,
        "rounds": len(finished),
        "subjects": per_subject,
        "timeline": [
            {
                "round_id": r.id,
                "subject": subjects.get(r.subject_id, "?"),
                "at": r.finished_at,
                "accuracy": round(r.score / r.total, 3) if r.total else None,
            }
            for r in sorted(finished, key=lambda r: r.finished_at or r.started_at)
        ],
    }


@router.get("/learning/subjects/{subject_id}")
def subject_detail(subject_id: int, user: Learner, db: Db) -> dict[str, Any]:
    pr.ensure_starter_questions(db)
    subject = _subject(db, subject_id)
    account = _account(db, user)
    questions = _visible(db, subject.id)
    rounds = _rounds(db, account.id, subject.id)
    prog = pr.subject_progress(rounds, {q.topic for q in questions})
    open_ = next((r for r in reversed(rounds) if r.finished_at is None), None)
    return {
        "id": subject.id,
        "name": subject.name,
        "questions": len(questions),
        "open_round": open_.id if open_ else None,
        "improvement": pr.improvement(prog["trend"]),
        **prog,
    }


# --- students: a practice round -------------------------------------------------------------------


class RoundQuestion(BaseModel):
    id: int
    topic: str
    text: str
    options: list[str]  # in this round's (shuffled) order
    reason: str
    reason_text: str
    # once answered
    choice: int | None = None
    correct: bool | None = None
    answer: int | None = None
    explanation: str | None = None


class RoundOut(BaseModel):
    id: int
    subject_id: int
    subject: str
    focus: list[str]
    questions: list[RoundQuestion]
    score: int
    total: int
    finished_at: datetime | None


def _round_out(db: Store, rnd: m.PracticeRound) -> RoundOut:
    subject = db.get(m.Subject, rnd.subject_id)
    ids = [p["id"] for p in rnd.plan]
    bank = {q.id: q for q in db.find(m.BankQuestion, {"id": {"$in": ids}})}
    done = {r["id"]: r for r in rnd.results}
    out = []
    for p in rnd.plan:
        q = bank.get(p["id"])
        if q is None:  # deleted by a teacher since
            continue
        order: list[int] = p.get("order") or list(range(len(q.options)))
        row = RoundQuestion(
            id=q.id,
            topic=q.topic,
            text=q.text,
            options=[q.options[i] for i in order if i < len(q.options)],
            reason=p["reason"],
            reason_text=pr.REASONS.get(p["reason"], ""),
        )
        if q.id in done:
            r = done[q.id]
            row.choice = r["choice"]
            row.correct = r["correct"]
            row.answer = order.index(q.answer) if q.answer in order else None
            row.explanation = q.explanation
        out.append(row)
    return RoundOut(
        id=rnd.id,
        subject_id=rnd.subject_id,
        subject=subject.name if subject else "?",
        focus=rnd.focus,
        questions=out,
        score=rnd.score,
        total=rnd.total,
        finished_at=rnd.finished_at,
    )


@router.post("/learning/subjects/{subject_id}/rounds", status_code=201)
def start_round(subject_id: int, user: Learner, db: Db, topics: str | None = None) -> RoundOut:
    """The next round of 10, leaning towards the student's weak topics. An unfinished round in
    this subject is returned instead of starting another. ``topics`` (comma-separated) limits
    the round to those topics (a roadmap week's practice); it closes an unfinished round first."""
    pr.ensure_starter_questions(db)
    subject = _subject(db, subject_id)
    account = _account(db, user)
    rounds = _rounds(db, account.id, subject.id)
    open_ = next((r for r in reversed(rounds) if r.finished_at is None), None)
    wanted = [t.strip() for t in (topics or "").split(",") if t.strip()]
    if open_ is not None and not wanted:
        return _round_out(db, open_)
    if open_ is not None:  # a focused round replaces the unfinished one
        if open_.results:
            open_.finished_at, open_.total = datetime.now(UTC), len(open_.results)
        else:
            db.delete(open_)
            rounds.remove(open_)
        db.commit()
    pool = _visible(db, subject.id)
    if wanted:
        pool = [q for q in pool if q.topic in wanted]
        if not pool:
            raise HTTPException(422, "There are no questions on those topics yet.")
    finished = [r for r in rounds if r.finished_at is not None]
    try:
        plan = pr.plan_round(
            pool,
            pr.results_of(rounds),
            last_round=[p["id"] for p in finished[-1].plan] if finished else (),
        )
    except PracticeError as exc:
        raise _bad(exc) from exc
    rng = random.Random()
    rnd = m.PracticeRound(
        student_id=account.id,
        subject_id=subject.id,
        plan=[
            {
                "id": p.question.id,
                "topic": p.question.topic,
                "reason": p.reason,
                "order": rng.sample(range(len(p.question.options)), len(p.question.options)),
            }
            for p in plan.picks
        ],
        focus=wanted or plan.focus,
        total=len(plan.picks),
    )
    db.add(rnd)
    db.commit()
    return _round_out(db, rnd)


@router.get("/learning/rounds/{round_id}")
def get_round(round_id: int, user: Learner, db: Db) -> RoundOut:
    rnd = db.get(m.PracticeRound, round_id)
    if rnd is None or rnd.student_id != user.account_id:
        raise HTTPException(404, "No such round.")
    return _round_out(db, rnd)


class AnswerIn(BaseModel):
    question_id: int
    choice: int = Field(ge=0, le=10)  # index in the round's shown order


class AnswerOut(BaseModel):
    correct: bool
    answer: int  # the right option, in the shown order
    explanation: str
    score: int
    answered: int
    total: int
    finished: bool


@router.post("/learning/rounds/{round_id}/answer")
def answer(round_id: int, body: AnswerIn, user: Learner, db: Db) -> AnswerOut:
    """Checks one answer straight away (each question can be answered once)."""
    rnd = db.get(m.PracticeRound, round_id)
    if rnd is None or rnd.student_id != user.account_id:
        raise HTTPException(404, "No such round.")
    if rnd.finished_at is not None:
        raise HTTPException(409, "This round is finished. Start a new one.")
    entry = next((p for p in rnd.plan if p["id"] == body.question_id), None)
    if entry is None:
        raise HTTPException(404, "That question is not in this round.")
    if any(r["id"] == body.question_id for r in rnd.results):
        raise HTTPException(409, "You already answered this question.")
    q = db.get(m.BankQuestion, body.question_id)
    if q is None:
        raise HTTPException(404, "That question was removed by a teacher.")
    order: list[int] = entry.get("order") or list(range(len(q.options)))
    if body.choice >= len(order):
        raise HTTPException(422, "Pick one of the options.")
    correct = order[body.choice] == q.answer
    rnd.results = [
        *rnd.results,
        {
            "id": q.id,
            "topic": q.topic,
            "choice": body.choice,
            "correct": correct,
            "at": datetime.now(UTC),
        },
    ]
    rnd.score += int(correct)
    live = {p["id"] for p in rnd.plan} & {
        qid
        for (qid,) in db.values(
            m.BankQuestion, ["id"], {"id": {"$in": [p["id"] for p in rnd.plan]}}
        )
    }
    finished = len({r["id"] for r in rnd.results} & live) >= len(live)
    if finished:
        rnd.finished_at = datetime.now(UTC)
        rnd.total = len(rnd.results)
    db.commit()
    return AnswerOut(
        correct=correct,
        answer=order.index(q.answer),
        explanation=q.explanation,
        score=rnd.score,
        answered=len(rnd.results),
        total=rnd.total,
        finished=finished,
    )


@router.post("/learning/rounds/{round_id}/finish")
def finish_early(round_id: int, user: Learner, db: Db) -> RoundOut:
    """Ends a round before every question is answered (only answered ones count)."""
    rnd = db.get(m.PracticeRound, round_id)
    if rnd is None or rnd.student_id != user.account_id:
        raise HTTPException(404, "No such round.")
    if rnd.finished_at is None:
        if not rnd.results:
            db.delete(rnd)
            db.commit()
            raise HTTPException(410, "The round was empty, so it was discarded.")
        rnd.finished_at = datetime.now(UTC)
        rnd.total = len(rnd.results)
        db.commit()
    return _round_out(db, rnd)


# --- teachers: question banks ---------------------------------------------------------------------


def _teaching(db: Store, user: User) -> tuple[m.Account, set[int]]:
    account = _account(db, user)
    subjects = {sid for (sid,) in db.values(m.Folder, ["subject_id"], {"teacher_id": account.id})}
    return account, subjects


def _bank_subject(db: Store, user: User, subject_id: int) -> tuple[m.Account, m.Subject]:
    account, subjects = _teaching(db, user)
    if subject_id not in subjects:
        raise HTTPException(403, "Open a folder for this subject first to manage its questions.")
    return account, _subject(db, subject_id)


class BankQuestionOut(BaseModel):
    id: int
    topic: str
    text: str
    options: list[str]
    answer: int
    explanation: str
    difficulty: int
    starter: bool
    mine: bool
    author: str | None
    edited: bool
    hidden: bool
    answered: int
    right_rate: float | None


class BankOut(BaseModel):
    subject_id: int
    subject: str
    topics: list[str]
    questions: list[BankQuestionOut]


@router.get("/bank/{subject_id}")
def bank(subject_id: int, user: Teacher, db: Db) -> BankOut:
    pr.ensure_starter_questions(db)
    account, subject = _bank_subject(db, user, subject_id)
    rows = db.find(m.BankQuestion, {"subject_id": subject.id}, sort=[("topic", 1), ("id", 1)])
    stats = pr.question_stats(db.find(m.PracticeRound, {"subject_id": subject.id}))
    names = {
        a.id: a.name
        for a in db.find(
            m.Account, {"id": {"$in": list({q.author_id for q in rows if q.author_id})}}
        )
    }
    out = []
    for q in rows:
        n, right = stats.get(q.id, (0, 0))
        out.append(
            BankQuestionOut(
                id=q.id,
                topic=q.topic,
                text=q.text,
                options=q.options,
                answer=q.answer,
                explanation=q.explanation,
                difficulty=q.difficulty,
                starter=q.seed_key is not None,
                mine=q.author_id == account.id,
                author=names.get(q.author_id or "") if q.author_id else None,
                edited=q.edited,
                hidden=q.hidden,
                answered=n,
                right_rate=round(right / n, 3) if n else None,
            )
        )
    return BankOut(
        subject_id=subject.id,
        subject=subject.name,
        topics=sorted({q.topic for q in rows}),
        questions=out,
    )


class QuestionIn(BaseModel):
    topic: str = Field(max_length=80)
    text: str = Field(max_length=2100)
    options: list[str] = Field(max_length=6)
    answer: int
    explanation: str = Field(default="", max_length=2100)
    difficulty: int = 2


@router.post("/bank/{subject_id}/questions", status_code=201)
def add_question(subject_id: int, body: QuestionIn, user: Teacher, db: Db) -> dict[str, int]:
    account, subject = _bank_subject(db, user, subject_id)
    try:
        clean = pr.clean_question(body.model_dump())
    except PracticeError as exc:
        raise _bad(exc) from exc
    q = m.BankQuestion(subject_id=subject.id, author_id=account.id, **clean)
    db.add(q)
    db.commit()
    return {"id": q.id}


def _editable(db: Store, user: User, question_id: int) -> tuple[m.Account, m.BankQuestion]:
    q = db.get(m.BankQuestion, question_id)
    if q is None:
        raise HTTPException(404, "No such question.")
    account, _ = _bank_subject(db, user, q.subject_id)
    if q.seed_key is None and q.author_id != account.id:
        raise HTTPException(403, "Only the teacher who wrote this question can change it.")
    return account, q


@router.post("/bank/questions/{question_id}")
def edit_question(question_id: int, body: QuestionIn, user: Teacher, db: Db) -> dict[str, int]:
    """Teachers edit their own questions and the starter questions of their subjects."""
    _, q = _editable(db, user, question_id)
    try:
        clean = pr.clean_question(body.model_dump())
    except PracticeError as exc:
        raise _bad(exc) from exc
    for k, v in clean.items():
        setattr(q, k, v)
    q.edited = q.seed_key is not None or q.edited
    q.updated_at = datetime.now(UTC)
    db.commit()
    return {"id": q.id}


class HiddenIn(BaseModel):
    hidden: bool


@router.post("/bank/questions/{question_id}/hidden", status_code=204)
def hide_question(question_id: int, body: HiddenIn, user: Teacher, db: Db) -> None:
    """Hidden questions stay in the bank (and in past results) but are not asked any more."""
    _, q = _editable(db, user, question_id)
    q.hidden = body.hidden
    db.commit()


@router.delete("/bank/questions/{question_id}", status_code=204)
def delete_question(question_id: int, user: Teacher, db: Db) -> None:
    _, q = _editable(db, user, question_id)
    if q.seed_key is not None:
        raise HTTPException(409, "Starter questions cannot be deleted; hide them instead.")
    db.delete_many(m.BankQuestion, {"id": q.id})
    db.commit()


class ImportOut(BaseModel):
    added: int
    problems: list[str]


@router.post("/bank/{subject_id}/import")
async def import_csv(subject_id: int, file: UploadFile, user: Teacher, db: Db) -> ImportOut:
    """CSV with columns topic, question, option_a ... option_d (up to option_f), answer (A-F or
    the right option's text), and optional explanation, difficulty. Good rows are added; the
    others are reported."""
    account, subject = _bank_subject(db, user, subject_id)
    data = await file.read(1_000_001)
    if len(data) > 1_000_000:
        raise HTTPException(413, "Please upload at most 1 MB of questions at a time.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "Save the CSV as UTF-8 and try again.") from exc
    reader = csv.DictReader(io.StringIO(text))
    header = {(h or "").strip().lower() for h in reader.fieldnames or []}
    missing = [
        c for c in ("topic", "question", "option_a", "option_b", "answer") if c not in header
    ]
    if missing:
        raise HTTPException(422, f"The CSV needs these columns: {', '.join(missing)}.")
    rows = list(reader)
    if len(rows) > 1000:
        raise HTTPException(422, "Please upload at most 1000 questions at a time.")
    good, problems = pr.parse_csv_rows(rows)
    for clean in good:
        db.add(m.BankQuestion(subject_id=subject.id, author_id=account.id, **clean))
    db.commit()
    return ImportOut(added=len(good), problems=problems[:50])


@router.get("/bank")
def my_banks(user: Teacher, db: Db) -> list[dict[str, Any]]:
    """The subjects whose question banks this teacher manages."""
    pr.ensure_starter_questions(db)
    account, subjects = _teaching(db, user)
    out = []
    for s in db.find(m.Subject, {"id": {"$in": list(subjects)}}, sort=[("name", 1)]):
        out.append(
            {
                "id": s.id,
                "name": s.name,
                "questions": db.count(m.BankQuestion, {"subject_id": s.id, "hidden": False}),
                "mine": db.count(m.BankQuestion, {"subject_id": s.id, "author_id": account.id}),
            }
        )
    return out


@router.get("/folders/{folder_id}/practice")
def folder_practice(folder_id: int, user: Teacher, db: Db) -> dict[str, Any]:
    """Practice results of the folder's enrolled students in its subject (for the analysis)."""
    folder = db.get(m.Folder, folder_id)
    if folder is None or folder.teacher_id != user.account_id:
        raise HTTPException(404, "This folder does not exist (any more).")
    students = [
        e.student_id for e in db.find(m.Enrollment, {"folder_id": folder.id}, sort=[("id", 1)])
    ]
    rounds = db.find(
        m.PracticeRound,
        {"subject_id": folder.subject_id, "student_id": {"$in": students}},
        sort=[("started_at", 1)],
    )
    by_student: dict[str, list[m.PracticeRound]] = {}
    for r in rounds:
        by_student.setdefault(r.student_id, []).append(r)
    rows = []
    for sid in students:
        prog = pr.subject_progress(by_student.get(sid, []))
        account = db.get(m.Account, sid)
        if account is None:
            continue
        rows.append(
            {
                "student": {
                    "username": account.username,
                    "name": account.name,
                    "has_photo": db.get(m.AccountPhoto, account.id) is not None,
                },
                "answered": prog["answered"],
                "accuracy": prog["accuracy"],
                "rounds": prog["rounds"],
                "strengths": prog["strengths"],
                "weaknesses": prog["weaknesses"],
            }
        )
    class_prog = pr.subject_progress(rounds)
    return {"topics": class_prog["topics"], "students": rows}


# --- the Progress page --------------------------------------------------------------------------


def _pct(right: int, answered: int) -> float | None:
    return round(right / answered, 3) if answered else None


@router.get("/progress/overview")
def progress_overview(user: Learner, db: Db, days: int = 30, tz: int = 0) -> dict[str, Any]:
    """Real performance across all subjects: My Learning answers bucketed by day (or by week for
    long ranges), per-subject and per-topic results, quiz scores and roadmap progress.
    ``days`` is the range (0 = everything); ``tz`` the browser's offset from UTC in minutes."""
    from mentora import roadmaps as rm

    pr.ensure_starter_questions(db)
    account = _account(db, user)
    offset = timedelta(minutes=max(-840, min(840, tz)))
    now = datetime.now(UTC)
    today = (now + offset).date()
    names = {s.id: s.name for s in db.find(m.Subject)}
    rounds = _rounds(db, account.id)

    answers: list[tuple[date, int, str, bool]] = []  # (local day, subject, topic, correct)
    for r in rounds:
        for res in r.results:
            at = res.get("at")
            if isinstance(at, datetime):
                at = at if at.tzinfo else at.replace(tzinfo=UTC)
                answers.append(
                    ((at + offset).date(), r.subject_id, res["topic"], bool(res["correct"]))
                )
    answers.sort(key=lambda a: a[0])

    first = answers[0][0] if answers else today
    start = first if days <= 0 else max(first, today - timedelta(days=days - 1))
    weekly = (today - start).days + 1 > 45
    if weekly:
        start -= timedelta(days=start.weekday())  # weeks start on Monday
    step = timedelta(days=7 if weekly else 1)
    buckets: list[date] = []
    d = start
    while d <= today:
        buckets.append(d)
        d += step

    def bucket_of(day: date) -> int:
        return (day - start).days // (7 if weekly else 1)

    in_range = [a for a in answers if a[0] >= start]
    subjects_seen = sorted({a[1] for a in answers}, key=lambda s: names.get(s, ""))
    per: dict[int, list[list[int]]] = {s: [[0, 0] for _ in buckets] for s in subjects_seen}
    overall = [[0, 0] for _ in buckets]
    for day, sid, _topic, ok in in_range:
        i = bucket_of(day)
        if 0 <= i < len(buckets):
            per[sid][i][0] += 1
            per[sid][i][1] += ok
            overall[i][0] += 1
            overall[i][1] += ok

    # running accuracy: where you stand overall at the end of each day / week
    seen_n = sum(1 for a in answers if a[0] < start)
    seen_ok = sum(a[3] for a in answers if a[0] < start)
    running = []
    for cell in overall:
        seen_n += cell[0]
        seen_ok += cell[1]
        running.append(_pct(seen_ok, seen_n))

    def window(sid: int, lo: int, hi: int) -> float | None:
        rows = [a for a in answers if a[1] == sid and lo <= (today - a[0]).days < hi]
        return _pct(sum(a[3] for a in rows), len(rows))

    subject_rows: list[dict[str, Any]] = []
    for sid in subjects_seen:
        rows = [a for a in answers if a[1] == sid]
        stats = pr.topic_stats({"topic": a[2], "correct": a[3]} for a in rows)
        topics = sorted(
            (
                {
                    "topic": s.topic,
                    "answered": s.answered,
                    "accuracy": _pct(s.right, s.answered),
                    "label": pr.label(s),
                }
                for s in stats.values()
            ),
            key=lambda t: t["accuracy"] or 0.0,
        )
        recent, previous = window(sid, 0, 7), window(sid, 7, 14)
        subject_rows.append(
            {
                "id": sid,
                "name": names.get(sid, "?"),
                "answered": len(rows),
                "accuracy": _pct(sum(a[3] for a in rows), len(rows)),
                "rounds": sum(
                    1 for r in rounds if r.subject_id == sid and r.finished_at is not None
                ),
                "last_practised": max(a[0] for a in rows).isoformat(),
                "change": round(recent - previous, 3)
                if recent is not None and previous is not None
                else None,
                "spark": [_pct(c[1], c[0]) for c in per[sid]],
                "topics": topics,
                "strongest": [t["topic"] for t in topics if t["label"] == "strong"][::-1][:3],
                "weakest": [t["topic"] for t in topics if t["label"] == "weak"][:3],
            }
        )

    # study streak: days in a row with answers, ending today (or yesterday)
    days_with = {a[0] for a in answers}
    streak = 0
    d = today if today in days_with else today - timedelta(days=1)
    while d in days_with:
        streak += 1
        d -= timedelta(days=1)

    attempts = db.find(
        m.QuizAttempt,
        {"student_id": account.id, "submitted_at": {"$ne": None}},
        sort=[("submitted_at", -1)],
    )
    quiz_titles = {
        q.id: q.title for q in db.find(m.Quiz, {"id": {"$in": list({a.quiz_id for a in attempts})}})
    }
    quiz_pcts = [a.score / a.max_score for a in attempts if a.max_score]

    maps = []
    for rmap in db.find(m.Roadmap, {"student_id": account.id, "status": {"$ne": "archived"}}):
        s = rm.summary(rmap, now)
        maps.append(
            {
                "id": rmap.id,
                "goal": rmap.goal,
                "subject": rmap.subject,
                "percent": s["percent"],
                "week": s["current_week"],
                "weeks": s["weeks_total"],
                "status": rmap.status,
            }
        )

    finished = sorted(
        (r for r in rounds if r.finished_at is not None),
        key=lambda r: r.finished_at or r.started_at,
        reverse=True,
    )
    activity: list[dict[str, Any]] = [
        {
            "kind": "round",
            "at": r.finished_at,
            "title": names.get(r.subject_id, "Practice") + " practice",
            "score": r.score,
            "total": r.total,
            "id": r.id,
        }
        for r in finished[:8]
    ]
    activity += [
        {
            "kind": "quiz",
            "at": a.submitted_at,
            "title": quiz_titles.get(a.quiz_id, "Quiz"),
            "score": a.score,
            "total": a.max_score,
            "id": a.id,
        }
        for a in attempts[:8]
    ]
    activity.sort(key=lambda x: x["at"], reverse=True)

    all_topics = [
        {**t, "subject": s["name"]}
        for s in subject_rows
        for t in s["topics"]
        if t["answered"] >= pr.MIN_EVIDENCE
    ]
    in_range_ok = sum(a[3] for a in in_range)
    return {
        "range_days": days,
        "granularity": "week" if weekly else "day",
        "labels": [b.isoformat() for b in buckets],
        "totals": {
            "answered": len(answers),
            "accuracy": _pct(sum(a[3] for a in answers), len(answers)),
            "answered_in_range": len(in_range),
            "accuracy_in_range": _pct(in_range_ok, len(in_range)),
            "rounds": len(finished),
            "study_days": len(days_with),
            "streak": streak,
            "subjects": len(subjects_seen),
            "quizzes": len(attempts),
            "quiz_average": round(sum(quiz_pcts) / len(quiz_pcts), 3) if quiz_pcts else None,
        },
        "series": {
            "overall": [_pct(c[1], c[0]) for c in overall],
            "running": running,
            "answered": [c[0] for c in overall],
            "subjects": [
                {
                    "id": sid,
                    "name": names.get(sid, "?"),
                    "values": [_pct(c[1], c[0]) for c in per[sid]],
                }
                for sid in subjects_seen
            ],
        },
        "subjects": subject_rows,
        "focus": sorted(all_topics, key=lambda t: t["accuracy"] or 0.0)[:6],
        "strong": sorted(all_topics, key=lambda t: -(t["accuracy"] or 0.0))[:6],
        "roadmaps": maps,
        "activity": activity[:10],
    }
