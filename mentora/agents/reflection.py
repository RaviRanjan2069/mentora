from __future__ import annotations

from mentora.agents.base import TurnContext, TutorAgent


class ReflectionCoach(TutorAgent):
    """Self-reflection: what happened, why, and what to do differently."""

    name = "ReflectionCoach"

    def task_text(self, ctx: TurnContext) -> str:
        goals = "\n".join(f"- {g}" for g in ctx.goals) or "(no goal was set)"
        base = super().task_text(ctx)
        return f"Session goals:\n{goals}\n\nMost recent task:\n{base}"
