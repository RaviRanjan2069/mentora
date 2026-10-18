from __future__ import annotations

from pathlib import Path

import pytest

from mentora.course import CourseSpec, load_course, upsert_course
from mentora.db import StoreFactory
from mentora.rag.embeddings import HashingEmbedder
from mentora.rag.ingest import (
    PassageDraft,
    build_passages,
    embed_passages,
    load_documents,
    store_passages,
)

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "data" / "sample" / "corpus"


@pytest.fixture
def course() -> CourseSpec:
    return load_course(ROOT / "data" / "concepts.yaml")


@pytest.fixture
def embedder() -> HashingEmbedder:
    return HashingEmbedder(384)


@pytest.fixture
def passages(course: CourseSpec, embedder: HashingEmbedder) -> list[PassageDraft]:
    return embed_passages(build_passages(load_documents(CORPUS), course, 300, 40), embedder)


@pytest.fixture
def ingested(
    session_factory: StoreFactory, course: CourseSpec, passages: list[PassageDraft]
) -> int:
    with session_factory.begin() as db:
        course_id = upsert_course(db, course).id
    store_passages(session_factory, course_id, passages)
    return course_id
