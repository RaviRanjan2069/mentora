"""MemoryService that recalls in-process but runs end-of-session curation as a Celery job."""

from __future__ import annotations

from mentora.memory.reflect_curate import ReflectiveMemory
from mentora.memory.service import RecalledItem


class QueuedMemory:
    def __init__(self, inner: ReflectiveMemory) -> None:
        self.inner = inner

    def recall(self, learner_id: str, course_id: int, query: str) -> list[RecalledItem]:
        return self.inner.recall(learner_id, course_id, query)

    def end_session(self, session_id: str) -> None:
        from mentora.worker import end_session_memory

        end_session_memory.delay(session_id)
