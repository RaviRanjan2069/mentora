"""Subjects, teachers' folders, study material and quizzes (D42).

A teacher has one folder per subject ("Java by Dr. Ravi Singh"); students enrol in a folder with
one click to read its material and take its quizzes. Uploaded files live in MongoDB, split into
chunks, within a size limit per file and in total (Atlas M0 holds 512 MB for everything).
This module has the rules; ``mentora.api.routes.subjects`` has the HTTP side.
"""

from __future__ import annotations

import re
import string
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from statistics import mean
from typing import Any

from mentora.db import Store
from mentora.db import models as m

DEFAULT_SUBJECTS = (
    "Java",
    "Python",
    "DBMS",
    "Machine Learning",
    "Data Structures",
    "Web Development",
    "Operating Systems",
    "Computer Networks",
)
CHUNK_BYTES = 1024 * 1024
STRONG, WEAK = 0.75, 0.5  # topic accuracy at or above / below


class SubjectError(ValueError):
    """A request that cannot be done; the message is safe to show."""


# --- subjects --------------------------------------------------------------------------------


def clean_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not 2 <= len(name) <= 60:
        raise SubjectError("A subject name needs 2-60 characters.")
    return name


def subject_key(name: str) -> str:
    return clean_name(name).casefold()


def ensure_default_subjects(db: Store) -> None:
    if db.count(m.Subject):
        return
    for name in DEFAULT_SUBJECTS:
        db.add(m.Subject(key=subject_key(name), name=name))
    db.flush()


def find_or_add_subject(db: Store, raw: str, account_id: str) -> m.Subject:
    """The subject with this name (any capitalisation), added if it is new."""
    name = clean_name(raw)
    existing = db.find_one(m.Subject, {"key": subject_key(name)})
    if existing is not None:
        return existing
    subject = m.Subject(key=subject_key(name), name=name, created_by=account_id)
    db.add(subject)
    db.flush()
    return subject


# --- files -----------------------------------------------------------------------------------

# extension -> (content type, check on the first bytes)
_ZIP, _OLE, _PDF = b"PK\x03\x04", b"\xd0\xcf\x11\xe0", b"%PDF"
FILE_TYPES: dict[str, tuple[str, bytes | None]] = {
    "pdf": ("application/pdf", _PDF),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", _ZIP),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", _ZIP),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", _ZIP),
    "doc": ("application/msword", _OLE),
    "ppt": ("application/vnd.ms-powerpoint", _OLE),
    "xls": ("application/vnd.ms-excel", _OLE),
    "zip": ("application/zip", _ZIP),
    "png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    "jpg": ("image/jpeg", b"\xff\xd8\xff"),
    "jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    # text: must be UTF-8
    "txt": ("text/plain", None),
    "md": ("text/plain", None),
    "csv": ("text/csv", None),
    "py": ("text/plain", None),
    "java": ("text/plain", None),
    "sql": ("text/plain", None),
    "c": ("text/plain", None),
    "cpp": ("text/plain", None),
    "ipynb": ("application/json", None),
}
# Opened in the browser; everything else downloads.
INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "text/plain"}


def safe_file_name(raw: str) -> str:
    base = raw.replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[^\w.\- ()]+", "_", base).strip(" .") or "file"
    return base[-120:]


def file_type(name: str, data: bytes) -> str:
    """The content type, from the extension and checked against the file's first bytes."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in FILE_TYPES:
        allowed = ", ".join(sorted(FILE_TYPES))
        raise SubjectError(f"This type of file cannot be uploaded. Allowed: {allowed}.")
    kind, magic = FILE_TYPES[ext]
    if magic is None:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SubjectError("Text files must be UTF-8.") from exc
    elif not data.startswith(magic):
        raise SubjectError(f"This file is not a real .{ext} file.")
    return kind


def storage_used(db: Store) -> int:
    return sum(size or 0 for (size,) in db.values(m.Resource, ["size"], {"kind": "file"}))


def store_file(db: Store, resource: m.Resource, data: bytes) -> None:
    resource.size = len(data)
    db.add(resource)
    db.flush()  # the resource id
    for n, start in enumerate(range(0, len(data), CHUNK_BYTES)):
        db.add(
            m.ResourceChunk(
                id=f"{resource.id}:{n}",
                resource_id=resource.id,
                n=n,
                data=data[start : start + CHUNK_BYTES],
            )
        )


def file_chunks(db: Store, resource_id: int) -> Iterator[bytes]:
    for (data,) in db.values(
        m.ResourceChunk, ["data"], {"resource_id": resource_id}, sort=[("n", 1)]
    ):
        yield bytes(data)


def check_link(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://[^\s/$.?#][^\s]*$", url, re.I) or len(url) > 2000:
        raise SubjectError("Please enter a full web address starting with https://")
    return url


# --- quizzes ---------------------------------------------------------------------------------


def clean_questions(raw: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Checked questions with stable ids; raises SubjectError naming the first problem."""
    if not raw:
        raise SubjectError("Add at least one question.")
    if len(raw) > 100:
        raise SubjectError("A quiz can have at most 100 questions.")
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for i, q in enumerate(raw, start=1):
        kind = str(q.get("kind", ""))
        text = " ".join(str(q.get("text", "")).split())
        where = f"Question {i}"
        if kind not in m.QUESTION_KINDS:
            raise SubjectError(f"{where}: unknown question type.")
        if not 1 <= len(text) <= 2000:
            raise SubjectError(f"{where}: write the question.")
        options = [" ".join(str(o).split()) for o in q.get("options") or []]
        answer = list(q.get("answer") or [])
        if kind == "true_false":
            options = ["True", "False"]
        if kind in ("single", "multiple", "true_false"):
            if kind != "true_false" and not 2 <= len(options) <= 8:
                raise SubjectError(f"{where}: give 2-8 options.")
            if any(not o or len(o) > 500 for o in options):
                raise SubjectError(f"{where}: an option is empty or too long.")
            try:
                picks = sorted({int(a) for a in answer})
            except (TypeError, ValueError) as exc:
                raise SubjectError(f"{where}: mark the right answer.") from exc
            if not picks or any(not 0 <= a < len(options) for a in picks):
                raise SubjectError(f"{where}: mark the right answer.")
            if kind != "multiple" and len(picks) != 1:
                raise SubjectError(f"{where}: mark exactly one right answer.")
            answer = picks
        else:
            options = []
            answer = [" ".join(str(a).split()) for a in answer if str(a).strip()]
            if not answer or any(len(a) > 200 for a in answer):
                raise SubjectError(f"{where}: give at least one accepted answer.")
        try:
            points = float(q.get("points", 1) or 1)
        except (TypeError, ValueError) as exc:
            raise SubjectError(f"{where}: points must be a number.") from exc
        if not 0 < points <= 100:
            raise SubjectError(f"{where}: points must be between 0 and 100.")
        qid = str(q.get("id") or "").strip()[:20] or f"q{i}"
        while qid in used:
            qid += "x"
        used.add(qid)
        out.append(
            {
                "id": qid,
                "kind": kind,
                "text": text,
                "options": options,
                "answer": answer,
                "points": points,
                "topic": " ".join(str(q.get("topic") or "").split())[:60],
            }
        )
    return out


def without_answers(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in q.items() if k != "answer"} for q in questions]


def _norm(text: str) -> str:
    text = " ".join(text.casefold().split())
    return text.strip(string.punctuation + " ")


def grade_one(question: Mapping[str, Any], given: Any) -> bool:
    kind = question["kind"]
    if kind == "short":
        return isinstance(given, str) and _norm(given) in {_norm(a) for a in question["answer"]}
    picks = given if isinstance(given, list) else [given]
    try:
        chosen = {int(p) for p in picks if p is not None and p != ""}
    except (TypeError, ValueError):
        return False
    return chosen == set(question["answer"])


def grade(
    questions: list[dict[str, Any]], answers: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], float, float]:
    """Per-question results, score and maximum score (each question all or nothing)."""
    results = []
    for q in questions:
        given = answers.get(q["id"])
        answered = given not in (None, "", [])
        ok = answered and grade_one(q, given)
        results.append(
            {
                "id": q["id"],
                "correct": bool(ok),
                "answered": bool(answered),
                "points": q["points"] if ok else 0.0,
            }
        )
    score = sum(r["points"] for r in results)
    return results, score, sum(q["points"] for q in questions)


# --- analysis --------------------------------------------------------------------------------


def _topic_of(q: Mapping[str, Any]) -> str:
    return q.get("topic") or "General"


def _topics(quizzes: Mapping[int, m.Quiz], attempts: list[m.QuizAttempt]) -> dict[str, list[bool]]:
    by_topic: dict[str, list[bool]] = defaultdict(list)
    for a in attempts:
        quiz = quizzes.get(a.quiz_id)
        if quiz is None:
            continue
        topic_of = {q["id"]: _topic_of(q) for q in quiz.questions}
        for r in a.results:
            if r["id"] in topic_of:
                by_topic[topic_of[r["id"]]].append(bool(r["correct"]))
    return by_topic


def _topic_rows(by_topic: Mapping[str, list[bool]]) -> list[dict[str, Any]]:
    rows = [
        {"topic": t, "accuracy": round(sum(v) / len(v), 3), "answers": len(v)}
        for t, v in by_topic.items()
        if v
    ]
    return sorted(rows, key=lambda r: (r["accuracy"], r["topic"]))


def _best(attempts: list[m.QuizAttempt]) -> dict[int, m.QuizAttempt]:
    """Each quiz's best submitted attempt."""
    best: dict[int, m.QuizAttempt] = {}
    for a in attempts:
        if a.submitted_at is None or not a.max_score:
            continue
        cur = best.get(a.quiz_id)
        if cur is None or a.score / a.max_score > cur.score / cur.max_score:
            best[a.quiz_id] = a
    return best


def student_summary(quizzes: Mapping[int, m.Quiz], attempts: list[m.QuizAttempt]) -> dict[str, Any]:
    """One student's results in one folder: best score per quiz, topics, strengths, weaknesses."""
    done = [a for a in attempts if a.submitted_at is not None]
    best = _best(done)
    percents = [a.score / a.max_score for a in best.values()]
    topics = _topic_rows(_topics(quizzes, done))
    return {
        "quizzes_taken": len(best),
        "average": round(mean(percents), 3) if percents else None,
        "last_activity": max((a.submitted_at for a in done if a.submitted_at), default=None),
        "topics": topics,
        "strengths": [t["topic"] for t in topics if t["accuracy"] >= STRONG][::-1],
        "weaknesses": [t["topic"] for t in topics if t["accuracy"] < WEAK],
    }


def quiz_stats(quiz: m.Quiz, attempts: list[m.QuizAttempt]) -> dict[str, Any]:
    """Class results for one quiz (each student's best attempt)."""
    done = [a for a in attempts if a.quiz_id == quiz.id and a.submitted_at is not None]
    best_by_student: dict[str, m.QuizAttempt] = {}
    for a in done:
        cur = best_by_student.get(a.student_id)
        if cur is None or a.score > cur.score:
            best_by_student[a.student_id] = a
    best = list(best_by_student.values())
    percents = [a.score / a.max_score for a in best if a.max_score]
    per_question = []
    for q in quiz.questions:
        marks = [r["correct"] for a in best for r in a.results if r["id"] == q["id"]]
        per_question.append(
            {
                "id": q["id"],
                "text": q["text"],
                "topic": _topic_of(q),
                "accuracy": round(sum(marks) / len(marks), 3) if marks else None,
            }
        )
    return {
        "id": quiz.id,
        "title": quiz.title,
        "published": quiz.published,
        "students": len(best),
        "attempts": len(done),
        "average": round(mean(percents), 3) if percents else None,
        "highest": round(max(percents), 3) if percents else None,
        "lowest": round(min(percents), 3) if percents else None,
        "questions": per_question,
    }


def folder_analysis(db: Store, folder: m.Folder) -> dict[str, Any]:
    """Everything the teacher's analysis page shows for one folder."""
    quizzes = {q.id: q for q in db.find(m.Quiz, {"folder_id": folder.id}, sort=[("id", 1)])}
    attempts = db.find(m.QuizAttempt, {"quiz_id": {"$in": list(quizzes)}}) if quizzes else []
    enrolled = db.find(m.Enrollment, {"folder_id": folder.id})
    by_student: dict[str, list[m.QuizAttempt]] = defaultdict(list)
    for a in attempts:
        by_student[a.student_id].append(a)
    students = []
    for e in enrolled:
        row = student_summary(quizzes, by_student.get(e.student_id, []))
        row["student_id"] = e.student_id
        row["enrolled_at"] = e.created_at
        students.append(row)
    done = [a for a in attempts if a.submitted_at is not None]
    return {
        "quizzes": [quiz_stats(q, attempts) for q in quizzes.values()],
        "students": students,
        "topics": _topic_rows(_topics(quizzes, done)),
    }
