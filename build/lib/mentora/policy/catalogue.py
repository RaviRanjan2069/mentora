"""The frozen action catalogue: every (agent, move, style) the policy may choose."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from mentora.logging_xapi.statements import ActionRef

CATALOGUE_FILE = Path(__file__).with_name("actions.yaml")

Agent = Literal["Planner", "Monitor", "ReflectionCoach", "ContentTutor", "PeerBroker"]
Style = Literal["Socratic", "Directive"]
Phase = Literal["forethought", "performance", "reflection"]

AGENTS: tuple[Agent, ...] = ("Planner", "Monitor", "ReflectionCoach", "ContentTutor", "PeerBroker")
WAIT = ActionRef(move="WAIT")
ESCALATE = ActionRef(move="ESCALATE")


class MoveSpec(BaseModel):
    name: str
    agent: Agent
    phases: list[Phase] = Field(min_length=1)
    styles: list[Style] = Field(min_length=1)
    needs_rag: bool
    unsolicited: bool
    description: str
    why: str


class Catalogue:
    def __init__(self, version: str, why_prefix: str, moves: dict[str, MoveSpec]) -> None:
        self.version = version
        self.why_prefix = why_prefix
        self.moves = moves
        actions = [
            ActionRef(agent=spec.agent, move=name, style=style)
            for name, spec in moves.items()
            for style in spec.styles
        ]
        self.actions: tuple[ActionRef, ...] = (*actions, WAIT, ESCALATE)
        self._by_id = {a.id: a for a in self.actions}

    def __iter__(self) -> Iterator[ActionRef]:
        return iter(self.actions)

    def __len__(self) -> int:
        return len(self.actions)

    def __contains__(self, action: object) -> bool:
        return isinstance(action, ActionRef) and action.id in self._by_id

    def get(self, action_id: str) -> ActionRef:
        try:
            return self._by_id[action_id]
        except KeyError:
            raise KeyError(f"{action_id!r} is not in action catalogue {self.version}") from None

    def spec(self, action: ActionRef) -> MoveSpec | None:
        """Move metadata; None for WAIT and ESCALATE."""
        return self.moves.get(action.move)

    def is_unsolicited(self, action: ActionRef) -> bool:
        spec = self.spec(action)
        return spec is not None and spec.unsolicited

    def why_line(self, action: ActionRef) -> str | None:
        spec = self.spec(action)
        return f"{self.why_prefix} {spec.why}" if spec else None


def load_catalogue(path: Path = CATALOGUE_FILE) -> Catalogue:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    moves = {name: MoveSpec(name=name, **spec) for name, spec in raw["moves"].items()}
    return Catalogue(str(raw["version"]), str(raw["why_prefix"]), moves)


@lru_cache(maxsize=1)
def default_catalogue() -> Catalogue:
    return load_catalogue()
