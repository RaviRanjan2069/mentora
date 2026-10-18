"""Memory across sessions through the real orchestrator."""

from __future__ import annotations

from mentora.config import get_settings
from mentora.db import StoreFactory
from mentora.db import models as m
from mentora.llm.backends.fake import FakeLLM
from mentora.logging_xapi.lrs_client import SqlLRSClient
from mentora.memory.reflect_curate import ReflectiveMemory
from mentora.rag.embeddings import HashingEmbedder

from .conftest import MakeOrch, tutor_reply, with_mode


def test_memory_from_one_session_is_used_in_the_next(
    make_orch: MakeOrch, session_factory: StoreFactory
) -> None:
    settings = with_mode("deploy")
    memory = ReflectiveMemory(settings, session_factory, embedder=HashingEmbedder(384))
    fake = FakeLLM(default=tutor_reply)
    orch = make_orch(settings, fake=fake, memory=memory)

    sid1 = orch.start_session("lrn_mem").session_id
    orch.handle_message(sid1, "My goal is to finish 2 for loop exercises today")
    orch.end_session(sid1)
    with session_factory() as db:
        items = db.find(m.MemoryItem, {"learner_id": "lrn_mem"})
    assert [i.status for i in items] == ["active"] and "for loop" in items[0].text

    start2 = orch.start_session("lrn_mem")  # open goal -> Planner.recall_past_goals
    assert start2.action_id == "Planner.recall_past_goals.Socratic"
    sid2 = start2.session_id
    prompt = fake.requests[-1].messages[-1].content
    assert "finish 2 for loop exercises" in prompt
    tutor = [
        s.tutor_action
        for s in SqlLRSClient(session_factory).query(session_id=sid2)
        if s.tutor_action is not None
    ]
    assert tutor[0].memory_item_ids == [items[0].id]
    orch.end_session(sid2)
    with session_factory() as db:
        item = db.get(m.MemoryItem, items[0].id)
        assert item is not None and item.n_plus + item.n_minus == 1  # outcome recorded


def test_static_mode_never_uses_memory(make_orch: MakeOrch, session_factory: StoreFactory) -> None:
    settings = with_mode("collect", app_mode="static")
    memory = ReflectiveMemory(settings, session_factory, embedder=HashingEmbedder(384))
    orch = make_orch(settings, memory=memory)
    sid = orch.start_session("lrn_static_mem").session_id
    orch.handle_message(sid, "My goal is to finish 2 for loop exercises today")
    orch.end_session(sid)
    with session_factory() as db:
        assert db.find(m.MemoryItem) == []
    assert get_settings().app.mode == "adaptive"  # the copy did not leak into global settings
