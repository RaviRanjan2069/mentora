"""Subjects, teachers' folders, study material and quizzes (D42); rules in mentora.subjects."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from mentora import subjects as sub
from mentora.api.deps import User, current_user, db_session, require_learner, require_teacher
from mentora.api.routes.accounts import PersonOut, _account, _person
from mentora.config.settings import Settings
from mentora.db import IntegrityError, Store
from mentora.db import models as m
from mentora.subjects import SubjectError

router = APIRouter(prefix="/api", tags=["subjects"])

Db = Annotated[Store, Depends(db_session)]
Me = Annotated[User, Depends(current_user)]
Learner = Annotated[User, Depends(require_learner)]
Teacher = Annotated[User, Depends(require_teacher)]

LATE_GRACE = timedelta(seconds=60)


def _settings(request: Request) -> Settings:
    s: Settings = request.app.state.settings
    return s


def _bad(exc: SubjectError) -> HTTPException:
    return HTTPException(422, str(exc))


def _folder(db: Store, folder_id: int) -> m.Folder:
    folder = db.get(m.Folder, folder_id)
    if folder is None:
        raise HTTPException(404, "This folder does not exist (any more).")
    return folder


def _own_folder(db: Store, user: User, folder_id: int) -> m.Folder:
    folder = _folder(db, folder_id)
    if folder.teacher_id != _account(db, user).id:
        raise HTTPException(404, "This folder does not exist (any more).")
    return folder


def _is_enrolled(db: Store, folder: m.Folder, account_id: str | None) -> bool:
    if account_id is None:
        return False
    return db.count(m.Enrollment, {"folder_id": folder.id, "student_id": account_id}) > 0


def _can_read(db: Store, user: User, folder: m.Folder) -> bool:
    """The folder's teacher, or a student enrolled in it."""
    if user.account_id is not None and folder.teacher_id == user.account_id:
        return True
    return user.role == "learner" and _is_enrolled(db, folder, user.account_id)


def _readable_folder(db: Store, user: User, folder_id: int) -> m.Folder:
    folder = _folder(db, folder_id)
    if not _can_read(db, user, folder):
        raise HTTPException(403, "Enrol in this folder to see its material and quizzes.")
    return folder


# --- subjects and folders ---------------------------------------------------------------------


class FolderOut(BaseModel):
    id: int
    subject_id: int
    subject: str
    teacher: PersonOut
    about: str
    resources: int
    quizzes: int
    students: int
    enrolled: bool
    mine: bool


class SubjectOut(BaseModel):
    id: int
    name: str
    folders: list[FolderOut]


def _folder_out(
    db: Store, folder: m.Folder, user: User, subject: m.Subject | None = None
) -> FolderOut:
    subject = subject or db.get(m.Subject, folder.subject_id)
    teacher = db.get(m.Account, folder.teacher_id)
    assert subject is not None and teacher is not None  # references cascade
    published = {"folder_id": folder.id, "published": True}
    mine = user.account_id == folder.teacher_id
    return FolderOut(
        id=folder.id,
        subject_id=subject.id,
        subject=subject.name,
        teacher=_person(db, teacher),
        about=folder.about,
        resources=db.count(m.Resource, {"folder_id": folder.id}),
        quizzes=db.count(m.Quiz, {"folder_id": folder.id} if mine else published),
        students=db.count(m.Enrollment, {"folder_id": folder.id}),
        enrolled=_is_enrolled(db, folder, user.account_id),
        mine=mine,
    )


@router.get("/subjects")
def list_subjects(user: Me, db: Db) -> list[SubjectOut]:
    """Every subject with its teachers' folders (subjects without folders included)."""
    sub.ensure_default_subjects(db)
    db.commit()
    folders: dict[int, list[m.Folder]] = {}
    for f in db.find(m.Folder, sort=[("id", 1)]):
        folders.setdefault(f.subject_id, []).append(f)
    out = []
    for s in db.find(m.Subject, sort=[("name", 1)]):
        out.append(
            SubjectOut(
                id=s.id,
                name=s.name,
                folders=[_folder_out(db, f, user, s) for f in folders.get(s.id, [])],
            )
        )
    return out


class FolderIn(BaseModel):
    subject: str = Field(min_length=1, max_length=80)  # an existing name or a new one
    about: str = Field(default="", max_length=1000)


@router.post("/folders", status_code=201)
def create_folder(body: FolderIn, user: Teacher, db: Db) -> FolderOut:
    """The teacher starts teaching a subject (adding the subject if it is new)."""
    account = _account(db, user)
    try:
        subject = sub.find_or_add_subject(db, body.subject, account.id)
    except SubjectError as exc:
        raise _bad(exc) from exc
    if db.count(m.Folder, {"subject_id": subject.id, "teacher_id": account.id}):
        raise HTTPException(409, f"You already have a {subject.name} folder.")
    folder = m.Folder(subject_id=subject.id, teacher_id=account.id, about=body.about.strip())
    db.add(folder)
    try:
        db.commit()
    except IntegrityError as exc:  # a subject or folder added at the same moment
        raise HTTPException(409, "Please try again.") from exc
    return _folder_out(db, folder, user, subject)


@router.get("/folders/{folder_id}")
def get_folder(folder_id: int, user: Me, db: Db) -> FolderOut:
    return _folder_out(db, _folder(db, folder_id), user)


class AboutIn(BaseModel):
    about: str = Field(default="", max_length=1000)


@router.post("/folders/{folder_id}")
def update_folder(folder_id: int, body: AboutIn, user: Teacher, db: Db) -> FolderOut:
    folder = _own_folder(db, user, folder_id)
    folder.about = body.about.strip()
    db.commit()
    return _folder_out(db, folder, user)


@router.delete("/folders/{folder_id}", status_code=204)
def delete_folder(folder_id: int, user: Teacher, db: Db) -> None:
    """Deletes the folder with its material, quizzes, results and enrolments."""
    folder = _own_folder(db, user, folder_id)
    db.delete_many(m.Folder, {"id": folder.id})
    db.commit()


@router.post("/folders/{folder_id}/enroll", status_code=201)
def enroll(folder_id: int, user: Learner, db: Db) -> FolderOut:
    account = _account(db, user)
    folder = _folder(db, folder_id)
    if not _is_enrolled(db, folder, account.id):
        db.add(m.Enrollment(folder_id=folder.id, student_id=account.id))
        try:
            db.commit()
        except IntegrityError:  # a double click
            db.rollback()
    return _folder_out(db, folder, user)


@router.delete("/folders/{folder_id}/enroll", status_code=204)
def leave(folder_id: int, user: Learner, db: Db) -> None:
    """Leaving keeps the student's quiz results (they come back if they enrol again)."""
    account = _account(db, user)
    db.delete_many(m.Enrollment, {"folder_id": folder_id, "student_id": account.id})
    db.commit()


class StudentOut(BaseModel):
    student: PersonOut
    enrolled_at: datetime


@router.delete("/folders/{folder_id}/students/{username}", status_code=204)
def remove_student(folder_id: int, username: str, user: Teacher, db: Db) -> None:
    folder = _own_folder(db, user, folder_id)
    student = db.find_one(m.Account, {"username": username.lower()})
    if student is not None:
        db.delete_many(m.Enrollment, {"folder_id": folder.id, "student_id": student.id})
        db.commit()


# --- material ---------------------------------------------------------------------------------


class ResourceOut(BaseModel):
    id: int
    kind: str
    title: str
    description: str
    url: str | None
    text: str | None
    file_name: str | None
    content_type: str | None
    size: int
    created_at: datetime


def _resource_out(r: m.Resource) -> ResourceOut:
    return ResourceOut(
        id=r.id,
        kind=r.kind,
        title=r.title,
        description=r.description,
        url=r.url,
        text=r.text,
        file_name=r.file_name,
        content_type=r.content_type,
        size=r.size,
        created_at=r.created_at,
    )


@router.get("/folders/{folder_id}/resources")
def list_resources(folder_id: int, user: Me, db: Db) -> list[ResourceOut]:
    folder = _readable_folder(db, user, folder_id)
    rows = db.find(m.Resource, {"folder_id": folder.id}, sort=[("id", -1)])
    return [_resource_out(r) for r in rows]


class LinkIn(BaseModel):
    kind: Literal["link", "note"]
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    url: str | None = Field(default=None, max_length=2000)
    text: str | None = Field(default=None, max_length=50_000)


@router.post("/folders/{folder_id}/resources", status_code=201)
def add_link_or_note(folder_id: int, body: LinkIn, user: Teacher, db: Db) -> ResourceOut:
    folder = _own_folder(db, user, folder_id)
    resource = m.Resource(
        folder_id=folder.id,
        kind=body.kind,
        title=" ".join(body.title.split()),
        description=body.description.strip(),
    )
    try:
        if body.kind == "link":
            resource.url = sub.check_link(body.url or "")
        else:
            if not (body.text or "").strip():
                raise SubjectError("Write the note.")
            resource.text = (body.text or "").strip()
    except SubjectError as exc:
        raise _bad(exc) from exc
    db.add(resource)
    db.commit()
    return _resource_out(resource)


class StorageOut(BaseModel):
    used: int
    total: int
    file_max: int


def _storage(db: Store, s: Settings) -> StorageOut:
    return StorageOut(
        used=sub.storage_used(db),
        total=int(s.subjects.storage_total_mb * 1024 * 1024),
        file_max=int(s.subjects.file_max_mb * 1024 * 1024),
    )


@router.get("/teacher/storage")
def storage(request: Request, user: Teacher, db: Db) -> StorageOut:
    return _storage(db, _settings(request))


@router.post("/folders/{folder_id}/files", status_code=201)
async def upload_file(
    folder_id: int,
    request: Request,
    user: Teacher,
    db: Db,
    file: UploadFile,
    title: Annotated[str, Form(max_length=200)] = "",
    description: Annotated[str, Form(max_length=1000)] = "",
) -> ResourceOut:
    folder = _own_folder(db, user, folder_id)
    room = _storage(db, _settings(request))
    data = await file.read(room.file_max + 1)
    if len(data) > room.file_max:
        raise HTTPException(
            413,
            f"Files can be up to {room.file_max // (1024 * 1024)} MB. "
            "For bigger material, upload it to Google Drive and add a link.",
        )
    if not data:
        raise HTTPException(422, "The file is empty.")
    if room.used + len(data) > room.total:
        raise HTTPException(
            507, "Mentora's storage for files is full. Add a link instead, or delete old files."
        )
    name = sub.safe_file_name(file.filename or "file")
    try:
        kind = sub.file_type(name, data)
    except SubjectError as exc:
        raise HTTPException(415, str(exc)) from exc
    resource = m.Resource(
        folder_id=folder.id,
        kind="file",
        title=" ".join(title.split()) or name.rsplit(".", 1)[0],
        description=description.strip(),
        file_name=name,
        content_type=kind,
    )
    sub.store_file(db, resource, data)
    db.commit()
    return _resource_out(resource)


@router.get("/resources/{resource_id}/file")
def download(resource_id: int, user: Me, db: Db) -> StreamingResponse:
    resource = db.get(m.Resource, resource_id)
    if resource is None or resource.kind != "file":
        raise HTTPException(404, "No such file.")
    _readable_folder(db, user, resource.folder_id)
    kind = resource.content_type or "application/octet-stream"
    how = "inline" if kind in sub.INLINE_TYPES else "attachment"
    name = resource.file_name or "file"
    if kind == "text/plain":
        kind = "text/plain; charset=utf-8"
    return StreamingResponse(
        sub.file_chunks(db, resource.id),
        media_type=kind,
        headers={
            "Content-Disposition": f"{how}; filename*=UTF-8''{quote(name)}",
            "Content-Length": str(resource.size),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete("/resources/{resource_id}", status_code=204)
def delete_resource(resource_id: int, user: Teacher, db: Db) -> None:
    resource = db.get(m.Resource, resource_id)
    if resource is None:
        return
    _own_folder(db, user, resource.folder_id)
    db.delete_many(m.Resource, {"id": resource.id})
    db.commit()


# --- quizzes ---------------------------------------------------------------------------------


class QuizIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    questions: list[dict[str, Any]] = Field(max_length=100)
    time_limit_min: int | None = Field(default=None, ge=1, le=600)
    max_attempts: int = Field(default=1, ge=1, le=20)
    show_answers: bool = True
    published: bool = False


class MyAttemptOut(BaseModel):
    id: int
    score: float
    max_score: float
    submitted_at: datetime | None
    late: bool


class QuizOut(BaseModel):
    id: int
    folder_id: int
    title: str
    description: str
    time_limit_min: int | None
    max_attempts: int
    show_answers: bool
    published: bool
    questions: list[dict[str, Any]]  # without answers for students
    question_count: int
    total_points: float
    updated_at: datetime
    # for students
    attempts: list[MyAttemptOut] = []
    attempts_left: int | None = None
    open_attempt: int | None = None
    # for the teacher
    taken_by: int | None = None


def _attempt_out(a: m.QuizAttempt) -> MyAttemptOut:
    return MyAttemptOut(
        id=a.id, score=a.score, max_score=a.max_score, submitted_at=a.submitted_at, late=a.late
    )


def _quiz_out(db: Store, quiz: m.Quiz, user: User, *, full: bool = True) -> QuizOut:
    mine = user.role == "teacher"
    out = QuizOut(
        id=quiz.id,
        folder_id=quiz.folder_id,
        title=quiz.title,
        description=quiz.description,
        time_limit_min=quiz.time_limit_min,
        max_attempts=quiz.max_attempts,
        show_answers=quiz.show_answers,
        published=quiz.published,
        questions=(quiz.questions if mine else sub.without_answers(quiz.questions)) if full else [],
        question_count=len(quiz.questions),
        total_points=sum(q["points"] for q in quiz.questions),
        updated_at=quiz.updated_at,
    )
    if mine:
        out.taken_by = len(db.distinct(m.QuizAttempt, "student_id", {"quiz_id": quiz.id}))
    elif user.account_id is not None:
        rows = db.find(
            m.QuizAttempt, {"quiz_id": quiz.id, "student_id": user.account_id}, sort=[("id", 1)]
        )
        done = [a for a in rows if a.submitted_at is not None]
        out.attempts = [_attempt_out(a) for a in done]
        out.attempts_left = max(0, quiz.max_attempts - len(done))
        open_ = next((a for a in rows if a.submitted_at is None), None)
        out.open_attempt = open_.id if open_ else None
    return out


def _quiz_for(db: Store, user: User, quiz_id: int) -> tuple[m.Quiz, m.Folder]:
    quiz = db.get(m.Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(404, "This quiz does not exist (any more).")
    folder = _readable_folder(db, user, quiz.folder_id)
    if user.role != "teacher" and not quiz.published:
        raise HTTPException(404, "This quiz does not exist (any more).")
    return quiz, folder


@router.get("/folders/{folder_id}/quizzes")
def list_quizzes(folder_id: int, user: Me, db: Db) -> list[QuizOut]:
    folder = _readable_folder(db, user, folder_id)
    query: dict[str, Any] = {"folder_id": folder.id}
    if user.role != "teacher":
        query["published"] = True
    return [_quiz_out(db, q, user, full=False) for q in db.find(m.Quiz, query, sort=[("id", -1)])]


@router.post("/folders/{folder_id}/quizzes", status_code=201)
def create_quiz(folder_id: int, body: QuizIn, user: Teacher, db: Db) -> QuizOut:
    folder = _own_folder(db, user, folder_id)
    try:
        questions = sub.clean_questions(body.questions)
    except SubjectError as exc:
        raise _bad(exc) from exc
    quiz = m.Quiz(
        folder_id=folder.id,
        title=" ".join(body.title.split()),
        description=body.description.strip(),
        questions=questions,
        time_limit_min=body.time_limit_min,
        max_attempts=body.max_attempts,
        show_answers=body.show_answers,
        published=body.published,
    )
    db.add(quiz)
    db.commit()
    return _quiz_out(db, quiz, user)


@router.get("/quizzes/{quiz_id}")
def get_quiz(quiz_id: int, user: Me, db: Db) -> QuizOut:
    quiz, _ = _quiz_for(db, user, quiz_id)
    return _quiz_out(db, quiz, user)


@router.post("/quizzes/{quiz_id}")
def update_quiz(quiz_id: int, body: QuizIn, user: Teacher, db: Db) -> QuizOut:
    quiz, folder = _quiz_for(db, user, quiz_id)
    _own_folder(db, user, folder.id)
    try:
        questions = sub.clean_questions(body.questions)
    except SubjectError as exc:
        raise _bad(exc) from exc
    if questions != quiz.questions and db.count(m.QuizAttempt, {"quiz_id": quiz.id}):
        raise HTTPException(
            409,
            "Students have already taken this quiz, so its questions cannot change. "
            "Make a new quiz instead (you can still rename it or hide it).",
        )
    quiz.title = " ".join(body.title.split())
    quiz.description = body.description.strip()
    quiz.questions = questions
    quiz.time_limit_min = body.time_limit_min
    quiz.max_attempts = body.max_attempts
    quiz.show_answers = body.show_answers
    quiz.published = body.published
    quiz.updated_at = datetime.now(UTC)
    db.commit()
    return _quiz_out(db, quiz, user)


@router.delete("/quizzes/{quiz_id}", status_code=204)
def delete_quiz(quiz_id: int, user: Teacher, db: Db) -> None:
    quiz, folder = _quiz_for(db, user, quiz_id)
    _own_folder(db, user, folder.id)
    db.delete_many(m.Quiz, {"id": quiz.id})
    db.commit()


class StartOut(BaseModel):
    attempt_id: int
    started_at: datetime
    deadline: datetime | None


def _deadline(quiz: m.Quiz, attempt: m.QuizAttempt) -> datetime | None:
    if quiz.time_limit_min is None:
        return None
    return attempt.started_at + timedelta(minutes=quiz.time_limit_min)


@router.post("/quizzes/{quiz_id}/start")
def start_quiz(quiz_id: int, user: Learner, db: Db) -> StartOut:
    """Starts an attempt, or returns the one already running."""
    quiz, _ = _quiz_for(db, user, quiz_id)
    account = _account(db, user)
    rows = db.find(m.QuizAttempt, {"quiz_id": quiz.id, "student_id": account.id})
    attempt = next((a for a in rows if a.submitted_at is None), None)
    if attempt is None:
        if sum(a.submitted_at is not None for a in rows) >= quiz.max_attempts:
            raise HTTPException(409, "You have used all your attempts for this quiz.")
        attempt = m.QuizAttempt(quiz_id=quiz.id, student_id=account.id)
        db.add(attempt)
        db.commit()
    return StartOut(
        attempt_id=attempt.id, started_at=attempt.started_at, deadline=_deadline(quiz, attempt)
    )


class SubmitIn(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)


class ResultOut(BaseModel):
    id: int
    quiz_id: int
    quiz_title: str
    student: PersonOut | None
    score: float
    max_score: float
    submitted_at: datetime | None
    late: bool
    show_answers: bool
    # each: id, text, kind, options, topic, points, given, correct, earned (+ answer if shown)
    questions: list[dict[str, Any]]


def _result(db: Store, quiz: m.Quiz, a: m.QuizAttempt, *, teacher: bool) -> ResultOut:
    show = teacher or quiz.show_answers
    results = {r["id"]: r for r in a.results}
    questions = []
    for q in quiz.questions:
        r = results.get(q["id"], {})
        row = {
            "id": q["id"],
            "text": q["text"],
            "kind": q["kind"],
            "options": q["options"],
            "topic": q.get("topic") or "",
            "points": q["points"],
            "given": a.answers.get(q["id"]),
            "correct": bool(r.get("correct")),
            "earned": r.get("points", 0.0),
        }
        if show:
            row["answer"] = q["answer"]
        questions.append(row)
    student = db.get(m.Account, a.student_id)
    return ResultOut(
        id=a.id,
        quiz_id=quiz.id,
        quiz_title=quiz.title,
        student=_person(db, student) if student else None,
        score=a.score,
        max_score=a.max_score,
        submitted_at=a.submitted_at,
        late=a.late,
        show_answers=show,
        questions=questions,
    )


@router.post("/attempts/{attempt_id}/submit")
def submit(attempt_id: int, body: SubmitIn, user: Learner, db: Db) -> ResultOut:
    account = _account(db, user)
    attempt = db.get(m.QuizAttempt, attempt_id)
    if attempt is None or attempt.student_id != account.id:
        raise HTTPException(404, "No such attempt.")
    if attempt.submitted_at is not None:
        raise HTTPException(409, "This attempt was already submitted.")
    quiz, _ = _quiz_for(db, user, attempt.quiz_id)
    ids = {q["id"] for q in quiz.questions}
    answers = {k: v for k, v in body.answers.items() if k in ids}
    results, score, max_score = sub.grade(quiz.questions, answers)
    now = datetime.now(UTC)
    deadline = _deadline(quiz, attempt)
    attempt.answers, attempt.results = answers, results
    attempt.score, attempt.max_score = score, max_score
    attempt.submitted_at = now
    attempt.late = deadline is not None and now > deadline + LATE_GRACE
    db.commit()
    return _result(db, quiz, attempt, teacher=False)


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: int, user: Me, db: Db) -> ResultOut:
    attempt = db.get(m.QuizAttempt, attempt_id)
    if attempt is None or attempt.submitted_at is None:
        raise HTTPException(404, "No such result.")
    quiz = db.get(m.Quiz, attempt.quiz_id)
    folder = db.get(m.Folder, quiz.folder_id) if quiz else None
    if quiz is None or folder is None:
        raise HTTPException(404, "No such result.")
    teacher = user.account_id == folder.teacher_id
    if not teacher and user.account_id != attempt.student_id:
        raise HTTPException(404, "No such result.")
    return _result(db, quiz, attempt, teacher=teacher)


# --- analysis --------------------------------------------------------------------------------


@router.get("/folders/{folder_id}/analysis")
def analysis(folder_id: int, user: Teacher, db: Db) -> dict[str, Any]:
    """Quiz results, each student's progress, strengths and weaknesses, and class topics."""
    folder = _own_folder(db, user, folder_id)
    data = sub.folder_analysis(db, folder)
    for row in data["students"]:
        account = db.get(m.Account, row.pop("student_id"))
        row["student"] = _person(db, account).model_dump() if account else None
        attempts = db.find(
            m.QuizAttempt,
            {"student_id": account.id if account else "", "submitted_at": {"$ne": None}},
            sort=[("submitted_at", -1)],
        )
        quiz_ids = {q["id"] for q in data["quizzes"]}
        row["recent"] = [
            {"attempt_id": a.id, "quiz_id": a.quiz_id, "score": a.score, "max_score": a.max_score}
            for a in attempts
            if a.quiz_id in quiz_ids
        ][:10]
    data["students"].sort(key=lambda r: (r["average"] is None, r["average"] or 0))
    return data


@router.get("/folders/{folder_id}/my-results")
def my_results(folder_id: int, user: Learner, db: Db) -> dict[str, Any]:
    folder = _readable_folder(db, user, folder_id)
    account = _account(db, user)
    quizzes = {q.id: q for q in db.find(m.Quiz, {"folder_id": folder.id, "published": True})}
    attempts = (
        db.find(
            m.QuizAttempt,
            {"quiz_id": {"$in": list(quizzes)}, "student_id": account.id},
            sort=[("submitted_at", -1)],
        )
        if quizzes
        else []
    )
    summary = sub.student_summary(quizzes, attempts)
    summary["attempts"] = [
        {
            **_attempt_out(a).model_dump(),
            "quiz_id": a.quiz_id,
            "quiz_title": quizzes[a.quiz_id].title,
        }
        for a in attempts
        if a.submitted_at is not None
    ]
    return summary


@router.get("/folders/{folder_id}/students")
def folder_students(folder_id: int, user: Teacher, db: Db) -> list[StudentOut]:
    folder = _own_folder(db, user, folder_id)
    out = []
    for e in db.find(m.Enrollment, {"folder_id": folder.id}, sort=[("id", 1)]):
        account = db.get(m.Account, e.student_id)
        if account is not None:
            out.append(StudentOut(student=_person(db, account), enrolled_at=e.created_at))
    return out


@router.get("/me/quizzes/pending")
def pending_quizzes(user: Learner, db: Db) -> list[dict[str, Any]]:
    """Published quizzes in the student's folders that they can still take (for Home)."""
    account = _account(db, user)
    folders = {e.folder_id for e in db.find(m.Enrollment, {"student_id": account.id})}
    out = []
    for q in db.find(
        m.Quiz, {"folder_id": {"$in": list(folders)}, "published": True}, sort=[("id", -1)]
    ):
        done = db.count(
            m.QuizAttempt,
            {"quiz_id": q.id, "student_id": account.id, "submitted_at": {"$ne": None}},
        )
        if done:
            continue
        folder = db.get(m.Folder, q.folder_id)
        subject = db.get(m.Subject, folder.subject_id) if folder else None
        teacher = db.get(m.Account, folder.teacher_id) if folder else None
        out.append(
            {
                "id": q.id,
                "title": q.title,
                "subject": subject.name if subject else "",
                "teacher": teacher.name if teacher else "",
                "questions": len(q.questions),
                "time_limit_min": q.time_limit_min,
            }
        )
    return out[:6]
