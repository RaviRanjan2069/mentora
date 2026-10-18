from __future__ import annotations

from mentora.agents.base import TurnContext, TutorAgent


class Planner(TutorAgent):
    """Forethought: goals, plans, time estimates and schedules."""

    name = "Planner"

    def task_text(self, ctx: TurnContext) -> str:
        goals = "\n".join(f"- {g}" for g in ctx.goals) or "(no active goal yet)"
        return f"Active goals:\n{goals}"
