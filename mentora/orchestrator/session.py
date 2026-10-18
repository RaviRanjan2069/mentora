"""Build a ready-to-use orchestrator from settings."""

from __future__ import annotations

from mentora.config.settings import Settings
from mentora.course import load_course, upsert_course
from mentora.db import StoreFactory
from mentora.db import models as m
from mentora.llm.client import LLMClient, make_client
from mentora.memory.service import MemoryService
from mentora.orchestrator.turn import Clock, Orchestrator
from mentora.policy.base import Proposer


def build_orchestrator(
    settings: Settings,
    session_factory: StoreFactory,
    *,
    client: LLMClient | None = None,
    memory: MemoryService | None = None,
    proposer: Proposer | None = None,
    clock: Clock | None = None,
) -> Orchestrator:
    course = load_course(settings.app.concepts_file)
    client = client or make_client(settings)
    with session_factory.begin() as db:
        course_id = upsert_course(db, course).id
        n_passages = db.count(m.CorpusPassage, {"course_id": course_id})
    rag = None
    if n_passages:
        from mentora.rag import build_pipeline

        rag = build_pipeline(settings, session_factory, course_id)
    if memory is None and settings.app.mode != "static":
        from mentora.memory.reflect_curate import ReflectiveMemory

        reflective = ReflectiveMemory(settings, session_factory, client=client)
        if settings.jobs.mode == "celery":
            from mentora.memory.queued import QueuedMemory

            memory = QueuedMemory(reflective)
        else:
            memory = reflective
    return Orchestrator(
        settings,
        session_factory,
        client=client,
        course=course,
        rag=rag,
        memory=memory,
        proposer=proposer,
        clock=clock,
    )
