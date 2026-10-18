"""M3 'done when': every action has a golden test (prompt + FakeLLM reply).

Regenerate after a deliberate prompt change with:  UPDATE_GOLDEN=1 pytest tests/unit/agents
then review the diff of tests/golden/agents/ like any other code change.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mentora.agents import TurnContext
from mentora.config import Settings
from mentora.llm.backends.fake import FakeLLM
from mentora.policy.catalogue import ESCALATE, WAIT, Catalogue, default_catalogue
from mentora.safety.feasibility import FilterContext, feasible_set

from .conftest import NOW, golden_reply, make_team, open_filter

GOLDEN_DIR = Path(__file__).resolve().parents[2] / "golden" / "agents"
ACTION_IDS = [a.id for a in default_catalogue()]


def _snapshot(action_id: str, catalogue: Catalogue, settings: Settings, ctx: TurnContext) -> str:
    action = catalogue.get(action_id)
    fake = FakeLLM(default=golden_reply)
    team = make_team(fake, settings, catalogue)
    allowed = open_filter(catalogue, settings)
    if action == ESCALATE:  # also cover the distress variant of ESCALATE
        distress = feasible_set(
            FilterContext(now=NOW, distress=True), [], catalogue=catalogue, settings=settings.safety
        )
        normal = team.respond(action, ctx, allowed)
        crisis = team.respond(action, ctx, distress)
        return (
            f"=== REPLY (policy escalation) ===\n{normal.text}\n"
            f"=== REPLY (distress) ===\n{crisis.text}\n"
        )
    reply = team.respond(action, ctx, allowed)
    if action == WAIT:
        assert not fake.requests
        return f"=== REPLY ===\n{reply.text}\n"
    [request] = fake.requests
    return (
        f"=== PROMPT VERSION ===\n{reply.prompt_version}\n"
        f"=== SYSTEM ===\n{request.system}\n"
        f"=== USER ===\n{request.messages[-1].content}\n"
        f"=== REPLY ===\n{reply.text}\n"
    )


@pytest.mark.parametrize("action_id", ACTION_IDS)
def test_golden(action_id: str, catalogue: Catalogue, settings: Settings, ctx: TurnContext) -> None:
    actual = _snapshot(action_id, catalogue, settings, ctx)
    path = GOLDEN_DIR / f"{action_id}.txt"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8", newline="\n")
    assert path.exists(), f"missing golden file {path.name}; run with UPDATE_GOLDEN=1"
    assert actual == path.read_text(encoding="utf-8")


def test_no_stale_golden_files() -> None:
    files = {p.stem for p in GOLDEN_DIR.glob("*.txt")}
    assert files == set(ACTION_IDS)
