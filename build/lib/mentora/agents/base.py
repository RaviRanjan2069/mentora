"""Shared generator for the five tutor agents.

The policy has already chosen the action (agent, move, style) from the feasible set; the
agent only phrases it with the LLM. Every reply ends with a fixed "why this suggestion"
line taken from the catalogue, never written by the LLM.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from mentora.config.settings import Settings
from mentora.llm.client import LLMClient
from mentora.llm.prompts import PromptRegistry, RenderedPrompt, default_registry
from mentora.logging_xapi.statements import ActionRef
from mentora.policy.catalogue import Agent, Catalogue, Phase
from mentora.rag.grounding import (
    ClaimDetector,
    EntailmentJudge,
    GroundingReport,
    grounded_generate,
)
from mentora.rag.retrieve import Passage
from mentora.safety.feasibility import FilterResult
from mentora.safety.integrity_check import ItemView, integrity_check

EscalationReason = Literal["distress", "grounding_failure", "policy"]
_TAG_RE = re.compile(r"</?\s*learner_message\s*>", re.IGNORECASE)


def _neutralize_tags(text: str | None) -> str | None:
    """Stop learner text from closing the <learner_message> data block."""
    return _TAG_RE.sub("[tag removed]", text) if text else text


class InfeasibleActionError(Exception):
    """An action outside F(s) reached an agent. This must never happen."""


@dataclass(frozen=True)
class TurnContext:
    course_title: str
    phase: Phase
    state_summary: str = "No learner state yet."
    learner_message: str | None = None
    memory_items: Sequence[str] = ()
    passages: Sequence[Passage] = ()
    item: ItemView | None = None
    target_concept: str | None = None
    goals: Sequence[str] = ()


@dataclass(frozen=True)
class AgentReply:
    action: ActionRef
    text: str | None  # None means send nothing (silent WAIT)
    why: str | None = None
    prompt_version: str | None = None
    model: str | None = None
    passage_ids: list[str] = field(default_factory=list)
    escalate: bool = False
    escalation_reason: EscalationReason | None = None
    show_support_resources: bool = False
    integrity_reasons: tuple[str, ...] = ()
    grounding: GroundingReport | None = None
    # Where the facts in the reply come from: "course" (verified against cited notes),
    # "general" (model knowledge; no course notes cover it) or "unverified" (cites notes
    # but could not be confirmed). None for replies that state no facts.
    answer_source: str | None = None


class TutorAgent:
    name: Agent

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
        self.client = client
        self.catalogue = catalogue
        self.settings = settings
        self.judge = judge
        self.detector = detector
        self.registry = registry or default_registry()

    # --- prompt -------------------------------------------------------------------------

    def task_text(self, ctx: TurnContext) -> str:
        if ctx.item is not None:
            text = f"Question: {ctx.item.text}"
            if ctx.target_concept:
                text += f"\nTarget concept: {ctx.target_concept}"
            if ctx.item.graded:
                text += "\nThis is a GRADED task: do not reveal the answer or a full solution."
            return text
        if ctx.target_concept:
            return f"Target concept: {ctx.target_concept}"
        return "No specific task right now."

    def memory_text(self, ctx: TurnContext) -> str:
        items = [f"- {m}" for m in ctx.memory_items]
        items += [f"- Goal: {g}" for g in ctx.goals]
        return "\n".join(items) or "(nothing yet)"

    def render(self, action: ActionRef, ctx: TurnContext) -> tuple[RenderedPrompt, str]:
        """The prompt for this action, and its composite version tag for logging."""
        spec = self.catalogue.spec(action)
        if spec is None or action.style is None:
            raise ValueError(f"{action.id} is not an agent action")
        reg = self.registry
        turn = reg.get("agents/turn")
        parts = [
            reg.fragment("agents/guards"),
            reg.fragment(f"agents/roles/{self.name}"),
            reg.fragment(f"agents/moves/{action.move}"),
            reg.fragment(f"agents/styles/{action.style}"),
        ]
        guards, role, move, style = parts
        passages = (
            "\n\n".join(f"[{p.id}] {p.text}" for p in ctx.passages) or "(none retrieved)"
            if spec.needs_rag
            else "(not needed for this move)"
        )
        rendered = turn.render(
            role=role.text,
            guards=guards.text,
            course_title=ctx.course_title,
            phase=ctx.phase,
            state_summary=ctx.state_summary,
            memory=self.memory_text(ctx),
            passages=passages,
            task=self.task_text(ctx),
            learner_message=_neutralize_tags(ctx.learner_message) or "(no message)",
            move_instruction=move.text,
            style_instruction=style.text,
            max_sentences=self.settings.agents.max_reply_sentences,
        )
        prompt = RenderedPrompt(
            id=f"agents/turn:{action.id}",
            version=turn.version,
            system=rendered.system,
            user=rendered.user,
        )
        tag = ";".join([turn.tag, *(p.tag for p in parts)])
        return prompt, tag

    # --- generation ---------------------------------------------------------------------

    def _generate(self, prompt: RenderedPrompt, feedback: str | None) -> str:
        if feedback:
            prompt = RenderedPrompt(
                prompt.id, prompt.version, prompt.system, f"{prompt.user}\n\n{feedback}"
            )
        return self.client.generate(prompt).strip()

    def respond(self, action: ActionRef, ctx: TurnContext, allowed: FilterResult) -> AgentReply:
        if not allowed.allows(action):
            raise InfeasibleActionError(f"{action.id} is outside the feasible set F(s)")
        if action.agent != self.name:
            raise ValueError(f"{self.name} cannot perform {action.id}")
        spec = self.catalogue.spec(action)
        assert spec is not None
        prompt, tag = self.render(action, ctx)
        safety = self.settings.safety

        grounding: GroundingReport | None = None
        escalate = False
        if spec.needs_rag:
            result = grounded_generate(
                lambda fb: self._generate(prompt, fb),
                {p.id: p.text for p in ctx.passages},
                self.judge,
                max_regenerations=self.settings.rag.max_regenerations,
                uncertain_reply=self.settings.rag.uncertain_reply,
                detector=self.detector,
                registry=self.registry,
            )
            text, grounding, escalate = result.text, result.report, result.escalate
            source: str | None = "course"
            if escalate and self.settings.rag.unverified == "label" and result.draft:
                # Show the reply, honestly labelled, instead of escalating every miss.
                text, escalate, source = result.draft, False, "unverified"
        else:
            source = None
            text = self._generate(prompt, None)

        integrity_reasons: tuple[str, ...] = ()
        for attempt in range(safety.integrity_regenerations + 1):
            check = integrity_check(text, ctx.item, max_code_lines=safety.max_solution_code_lines)
            if check.ok:
                break
            integrity_reasons = check.reasons
            if attempt == safety.integrity_regenerations:
                text = safety.integrity_fallback_reply
                break
            feedback = (
                "Your previous reply broke the academic-integrity rule for this graded task ("
                + "; ".join(check.reasons)
                + "). Rewrite it so it guides with a question and reveals no answer or solution."
            )
            text = self._generate(prompt, feedback)

        why = self.catalogue.why_line(action)
        calls = self.client.usage.calls
        return AgentReply(
            action=action,
            text=f"{text}\n\n{why}" if why else text,
            why=why,
            prompt_version=tag,
            model=calls[-1].model if calls else None,
            passage_ids=[p.id for p in ctx.passages] if spec.needs_rag else [],
            escalate=escalate,
            escalation_reason="grounding_failure" if escalate else None,
            integrity_reasons=integrity_reasons,
            grounding=grounding,
            answer_source=source if spec.needs_rag else None,
        )
