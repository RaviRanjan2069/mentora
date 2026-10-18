"""SRL indicator tagger and rubric scorers.

``llm`` mode labels each learner message with 8 binary indicators using a few-shot prompt,
and scores goal SMART quality and reflection quality with rubric prompts (JSON validated
by Pydantic). ``trace_only`` mode uses no LLM: keyword heuristics for the indicators and
checklist heuristics for the rubrics. The definitions match docs/coding_manual.md.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from mentora.config.settings import Settings
from mentora.llm.client import LLMClient
from mentora.llm.prompts import PromptRegistry, default_registry
from mentora.llm.types import LLMError


class SRLTags(BaseModel):
    goal_stated: bool = False
    plan_stated: bool = False
    strategy_named: bool = False
    monitoring_statement: bool = False
    help_request: bool = False
    self_evaluation: bool = False
    attribution: bool = False
    adaptation_intent: bool = False


INDICATORS: tuple[str, ...] = tuple(SRLTags.model_fields)


class RubricScore(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    rationale: str


_RULES: dict[str, re.Pattern[str]] = {
    "goal_stated": re.compile(
        r"\b(my goal|i want to|i('?d| would) like to|i aim to|i need to (learn|finish|understand)|"
        r"by the end of)\b",
        re.I,
    ),
    "plan_stated": re.compile(
        r"\b(first,? i|then i('?ll| will)|my plan|i('?ll| will) (start|begin)|step \d|"
        r"after that)\b",
        re.I,
    ),
    "strategy_named": re.compile(
        r"\b(practi[cs]e|re-?read|summari[sz]e|flashcards?|self-?test|explain it|"
        r"worked example|take notes|draw|trace (the|it))\b",
        re.I,
    ),
    "monitoring_statement": re.compile(
        r"\b(i (think i )?(get|understand|got) it|i'?m (not )?sure|i'?m (lost|confused)|"
        r"this (part )?is (hard|easy)|i (keep|still) (getting|making)|makes sense)\b",
        re.I,
    ),
    "help_request": re.compile(
        r"\b(help|hint|can you (explain|show)|i'?m stuck|what does .+ mean)\b|\?\s*$", re.I
    ),
    "self_evaluation": re.compile(
        r"\b(i did (well|badly|ok|okay)|went (well|badly)|i (got|scored) \d|"
        r"i (was|wasn'?t) (good|great|bad)|i (understood|messed up))\b",
        re.I,
    ),
    "attribution": re.compile(
        r"\b(because i|since i|due to|that'?s why|i (didn'?t|did not) (practi[cs]e|study|read))\b",
        re.I,
    ),
    "adaptation_intent": re.compile(
        r"\b(next time|from now on|i('?ll| will) (try|change|do)|i should (have|try)|instead i)\b",
        re.I,
    ),
}
_NUMBER_RE = re.compile(r"\b\d+\b|\b(one|two|three|four|five|ten)\b", re.I)
_TIME_RE = re.compile(
    r"\b(today|tonight|tomorrow|by \w+|this (week|session|evening)|minutes?|hours?|"
    r"before (the|my)|deadline|monday|tuesday|wednesday|thursday|friday|weekend)\b",
    re.I,
)
_VAGUE_RE = re.compile(r"\b(get better|learn (more|stuff)|do well|improve|study)\b\.?$", re.I)


def trace_tags(text: str) -> SRLTags:
    return SRLTags(**{k: bool(p.search(text)) for k, p in _RULES.items()})


def trace_goal_smart(goal: str) -> float:
    """Checklist: specific topic, measurable amount, time-bound, actionable verb, not vague."""
    words = goal.split()
    checks = [
        len(words) >= 5,
        bool(_NUMBER_RE.search(goal)),
        bool(_TIME_RE.search(goal)),
        bool(
            re.search(
                r"\b(finish|solve|complete|write|explain|practi[cs]e|read|answer)\b", goal, re.I
            )
        ),
        not _VAGUE_RE.search(goal.strip()),
    ]
    return sum(checks) / len(checks)


def trace_reflection_quality(text: str) -> float:
    """Checklist: describes what happened, evaluates, attributes, plans an adaptation."""
    tags = trace_tags(text)
    checks = [
        len(text.split()) >= 8,
        tags.self_evaluation or tags.monitoring_statement,
        tags.attribution,
        tags.adaptation_intent,
    ]
    return sum(checks) / len(checks)


class SRLTagger:
    def __init__(
        self,
        mode: Literal["llm", "trace_only"],
        client: LLMClient | None = None,
        registry: PromptRegistry | None = None,
    ) -> None:
        if mode == "llm" and client is None:
            raise ValueError("llm tagger mode needs an LLMClient")
        self.mode = mode
        self.client = client
        self.registry = registry or default_registry()

    @classmethod
    def from_settings(cls, settings: Settings, client: LLMClient | None) -> SRLTagger:
        mode = settings.learner_model.tagger_mode
        if mode == "auto":
            mode = "llm" if settings.llm.backend == "hosted" else "trace_only"
        return cls(mode, client if mode == "llm" else None)

    def tag(self, message: str, previous_turn: str | None = None) -> SRLTags:
        if self.mode == "trace_only" or self.client is None:
            return trace_tags(message)
        prompt = self.registry.get("learner_model/srl_tagger").render(
            message=message, previous=previous_turn or "(none)"
        )
        try:
            return self.client.generate(prompt, SRLTags, max_tokens=2000)
        except LLMError:
            return trace_tags(message)  # never block a turn on the tagger

    def _rubric(self, prompt_id: str, text: str, fallback: float) -> float:
        if self.mode == "trace_only" or self.client is None:
            return fallback
        prompt = self.registry.get(prompt_id).render(text=text)
        try:
            return self.client.generate(prompt, RubricScore, max_tokens=2000).score
        except LLMError:
            return fallback

    def goal_smart(self, goal: str) -> float:
        return self._rubric("learner_model/goal_smart", goal, trace_goal_smart(goal))

    def reflection_quality(self, text: str) -> float:
        return self._rubric(
            "learner_model/reflection_quality", text, trace_reflection_quality(text)
        )
