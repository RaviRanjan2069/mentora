"""Celery app for offline jobs: end-of-session memory curation, policy training and OPE."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from celery import Celery

from mentora.config import get_settings

celery_app = Celery("mentora", broker=get_settings().redis_url, backend=get_settings().redis_url)


@celery_app.task(name="mentora.ping")  # type: ignore[untyped-decorator]
def ping() -> str:
    return "pong"


@celery_app.task(name="mentora.end_session_memory")  # type: ignore[untyped-decorator]
def end_session_memory(session_id: str) -> dict[str, Any]:
    from mentora.db import make_engine, make_session_factory
    from mentora.llm.client import make_client
    from mentora.memory.reflect_curate import ReflectiveMemory

    settings = get_settings()
    memory = ReflectiveMemory(
        settings, make_session_factory(make_engine()), client=make_client(settings)
    )
    return asdict(memory.curate_session(session_id))


@celery_app.task(name="mentora.train_policy")  # type: ignore[untyped-decorator]
def train_policy() -> dict[str, Any]:
    from mentora.offline.train import run_offline_pipeline

    return run_offline_pipeline(get_settings()).as_dict()
