"""Interface between the orchestrator and reflective memory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RecalledItem:
    id: int
    text: str
    scope: str
    score: float


class MemoryService(Protocol):
    def recall(self, learner_id: str, course_id: int, query: str) -> list[RecalledItem]: ...

    def end_session(self, session_id: str) -> None: ...


class NullMemory:
    """No memory (static control condition, or before memory is enabled)."""

    def recall(self, learner_id: str, course_id: int, query: str) -> list[RecalledItem]:
        return []

    def end_session(self, session_id: str) -> None:
        return None
