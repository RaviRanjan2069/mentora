"""Planner, Monitor, ReflectionCoach, ContentTutor and PeerBroker, plus the team facade
that dispatches an already-chosen action. WAIT and ESCALATE never call the LLM."""

from __future__ import annotations

from mentora.agents.base import (
    AgentReply,
    InfeasibleActionError,
    TurnContext,
    TutorAgent,
)
from mentora.agents.content import ContentTutor
from mentora.agents.monitor import Monitor
from mentora.agents.peer import PeerBroker
from mentora.agents.planner import Planner
from mentora.agents.reflection import ReflectionCoach
from mentora.config.settings import Settings
from mentora.llm.client import LLMClient
from mentora.llm.prompts import PromptRegistry
from mentora.logging_xapi.statements import ActionRef
from mentora.policy.catalogue import ESCALATE, WAIT, Agent, Catalogue
from mentora.rag.grounding import ClaimDetector, EntailmentJudge
from mentora.safety.feasibility import FilterResult
from mentora.safety.wellbeing import support_message

AGENT_CLASSES: dict[Agent, type[TutorAgent]] = {
    "Planner": Planner,
    "Monitor": Monitor,
    "ReflectionCoach": ReflectionCoach,
    "ContentTutor": ContentTutor,
    "PeerBroker": PeerBroker,
}


class TutorTeam:
    def __init__(
        self,
        client: LLMClient,
        *,
        catalogue: Catalogue,
        settings: Settings,
        judge: EntailmentJudge,
        detector: ClaimDetector | None = None,
        registry: PromptRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.agents: dict[str, TutorAgent] = {
            name: cls(
                client,
                catalogue=catalogue,
                settings=settings,
                judge=judge,
                detector=detector,
                registry=registry,
            )
            for name, cls in AGENT_CLASSES.items()
        }

    def respond(self, action: ActionRef, ctx: TurnContext, allowed: FilterResult) -> AgentReply:
        if not allowed.allows(action):
            raise InfeasibleActionError(f"{action.id} is outside the feasible set F(s)")
        if action == WAIT:
            return AgentReply(action=action, text=None)
        if action == ESCALATE:
            distress = allowed.show_support_resources
            text = (
                support_message(self.settings.safety)
                if distress
                else self.settings.safety.escalate_reply
            )
            return AgentReply(
                action=action,
                text=text,
                escalate=True,
                escalation_reason="distress" if distress else "policy",
                show_support_resources=distress,
            )
        assert action.agent is not None
        return self.agents[action.agent].respond(action, ctx, allowed)


__all__ = [
    "AGENT_CLASSES",
    "AgentReply",
    "ContentTutor",
    "InfeasibleActionError",
    "Monitor",
    "PeerBroker",
    "Planner",
    "ReflectionCoach",
    "TurnContext",
    "TutorAgent",
    "TutorTeam",
]
