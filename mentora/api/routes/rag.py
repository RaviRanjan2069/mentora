from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from mentora.config.settings import Settings
from mentora.course import load_course
from mentora.db import models as m
from mentora.rag import build_pipeline
from mentora.rag.rerank import RagPipeline

router = APIRouter(prefix="/api/rag", tags=["rag"])


class Hit(BaseModel):
    id: str
    section: str | None
    week: int | None
    concepts: list[str]
    score: float
    text: str


class SearchResult(BaseModel):
    course: str
    query: str
    hits: list[Hit]


def _pipeline(request: Request) -> tuple[str, RagPipeline]:
    cached = getattr(request.app.state, "rag_pipeline", None)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    settings: Settings = request.app.state.settings
    factory = request.app.state.session_factory
    course = load_course(settings.app.concepts_file)
    with factory() as db:
        row = db.find_one(m.Course, {"code": course.code})
        course_id = row.id if row is not None else None
        has_passages = (
            course_id is not None and db.count(m.CorpusPassage, {"course_id": course_id}) > 0
        )
    if course_id is None or not has_passages:
        raise HTTPException(503, "No course material ingested yet. Run scripts/seed_demo.py.")
    request.app.state.rag_pipeline = (course.title, build_pipeline(settings, factory, course_id))
    return request.app.state.rag_pipeline  # type: ignore[no-any-return]


@router.get("/search")
def search(
    request: Request,
    q: Annotated[str, Query(min_length=2, max_length=500)],
    max_week: int | None = None,
) -> SearchResult:
    title, pipeline = _pipeline(request)
    hits = pipeline.search(q, max_week=max_week)
    return SearchResult(
        course=title,
        query=q,
        hits=[
            Hit(
                id=h.passage.id,
                section=h.passage.section,
                week=h.passage.week,
                concepts=list(h.passage.concept_keys),
                score=round(h.score, 4),
                text=h.passage.text,
            )
            for h in hits
        ],
    )
