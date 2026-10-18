from __future__ import annotations

from mentora.agents.base import TurnContext, TutorAgent


class PeerBroker(TutorAgent):
    """All phases: classmates, forum threads and peer strategies (no personal data)."""

    name = "PeerBroker"

    def task_text(self, ctx: TurnContext) -> str:
        base = super().task_text(ctx)
        return (
            f"{base}\nYou have no information about specific classmates or forum threads, "
            "so do not name any."
        )
