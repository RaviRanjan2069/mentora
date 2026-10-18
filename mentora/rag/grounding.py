"""Grounding check: every factual sentence must cite a retrieved passage id that entails it.

On failure the reply is regenerated once with feedback. If it still fails, the learner gets
an "I am not certain; I have asked your teacher" reply and an escalation is created.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from mentora.config import Settings
from mentora.db import StoreFactory
from mentora.db import models as m
from mentora.llm.client import LLMClient
from mentora.llm.prompts import PromptRegistry, default_registry
from mentora.rag.text import CITATION_RE, NEGATIONS, content_words, split_sentences, words

Status = Literal["ok", "non_factual", "no_citation", "unknown_passage", "not_entailed"]
_WHY_RE = re.compile(r"\bwhy this suggestion\s*:.*$", re.IGNORECASE | re.MULTILINE)
_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")

# Sentence openers that mark questions, instructions or social talk, not factual claims.
_NON_CLAIM_OPENERS = frozenset(
    """try think consider let let's lets take look write compare remember notice imagine pick
    choose start check ask reflect plan set note review practice read open go see what how why
    when where which who could would can do did does is are was were should shall may might
    you your i i'm i've we we're great good nice well sure okay ok thanks thank hi hello
    yes""".split()
)


# "According to the course notes," / "The passage says that" add nothing to judge and
# make NLI models hesitate; they are dropped before the claim is checked.
_ATTRIBUTION_RE = re.compile(
    r"^(according to|as stated in|as (it )?says in|based on|from) (the |this |your )?"
    r"(course )?(passage|notes|material|text)s?( above)?,?\s*"
    r"|^(the |this )?(course )?(passage|notes?|material) (says|states|explains) (that )?",
    re.IGNORECASE,
)


class EntailmentJudge(Protocol):
    def entails(self, premise: str, hypothesis: str) -> bool: ...


class ClaimDetector(Protocol):
    def is_claim(self, sentence: str) -> bool: ...


class HeuristicClaimDetector:
    """A declarative sentence of 4+ words that doesn't open like a question, instruction
    or social phrase counts as a factual claim. Deliberately strict (see decisions D14)."""

    def is_claim(self, sentence: str) -> bool:
        plain = CITATION_RE.sub("", sentence).strip()
        if not plain or plain.endswith("?") or len(words(plain)) < 4:
            return False
        first = words(plain)[0]
        return first not in _NON_CLAIM_OPENERS


class LexicalEntailmentJudge:
    """Offline stand-in: enough of the claim's content words appear in the premise, every
    number in the claim appears there too, and negation agrees."""

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold

    def entails(self, premise: str, hypothesis: str) -> bool:
        claim = content_words(hypothesis)
        if not claim:
            return True
        source = set(words(premise))
        coverage = sum(1 for w in claim if w in source) / len(claim)
        numbers_ok = set(_NUM_RE.findall(hypothesis)) <= set(_NUM_RE.findall(premise))
        neg_h = bool(NEGATIONS & set(words(hypothesis)))
        neg_p = bool(NEGATIONS & set(words(premise)))
        return coverage >= self.threshold and numbers_ok and (not neg_h or neg_p)


class NLIEntailmentJudge:
    """Cross-encoder NLI model; entailment must be the top label for some window of the
    premise. Small NLI models are reliable on one or two sentences but get confused by
    unrelated sentences elsewhere in a passage, so the premise is judged window by window."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: Any = None
        self._entail_idx = 1

    def entails(self, premise: str, hypothesis: str) -> bool:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name, device="cpu")
            labels = {v.lower(): k for k, v in self._model.config.id2label.items()}
            self._entail_idx = int(labels.get("entailment", 1))
        sentences = split_sentences(premise) or [premise]
        windows = [premise, *sentences]
        windows += [f"{a} {b}" for a, b in itertools.pairwise(sentences)]
        rows = self._model.predict([(w, hypothesis) for w in dict.fromkeys(windows)])
        return any(int(max(range(len(s)), key=lambda i: s[i])) == self._entail_idx for s in rows)


class EntailmentVerdict(BaseModel):
    supported: bool
    reason: str


class LLMEntailmentJudge:
    def __init__(self, client: LLMClient, registry: PromptRegistry | None = None) -> None:
        self.client = client
        self.registry = registry or default_registry()

    def entails(self, premise: str, hypothesis: str) -> bool:
        prompt = self.registry.get("rag/entailment_judge").render(
            premise=premise, hypothesis=hypothesis
        )
        return self.client.generate(prompt, EntailmentVerdict, max_tokens=2000).supported


def make_judge(settings: Settings, client: LLMClient | None = None) -> EntailmentJudge:
    kind = settings.rag.grounding_judge
    if kind == "lexical":
        return LexicalEntailmentJudge(settings.rag.lexical_entailment_threshold)
    if kind == "llm":
        if client is None:
            raise ValueError("the llm grounding judge needs an LLMClient")
        return LLMEntailmentJudge(client)
    return NLIEntailmentJudge(settings.rag.nli_model)


@dataclass(frozen=True)
class SentenceCheck:
    sentence: str
    cited_ids: tuple[str, ...]
    status: Status


@dataclass(frozen=True)
class GroundingReport:
    checks: tuple[SentenceCheck, ...]

    @property
    def failures(self) -> list[SentenceCheck]:
        return [c for c in self.checks if c.status not in ("ok", "non_factual")]

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def claims(self) -> list[SentenceCheck]:
        return [c for c in self.checks if c.status != "non_factual"]

    @property
    def faithfulness(self) -> float | None:
        """Share of factual sentences that are supported; None if there are none."""
        claims = self.claims
        return sum(c.status == "ok" for c in claims) / len(claims) if claims else None

    def problems(self) -> str:
        reasons = {
            "no_citation": "states a fact but cites no passage",
            "unknown_passage": "cites a passage id that was not provided",
            "not_entailed": "is not supported by the passage it cites",
        }
        return "\n".join(f'- "{c.sentence}" {reasons[c.status]}' for c in self.failures)


def check_grounding(
    reply: str,
    passages: Mapping[str, str],
    judge: EntailmentJudge,
    detector: ClaimDetector | None = None,
) -> GroundingReport:
    detector = detector or HeuristicClaimDetector()
    body = _WHY_RE.sub("", reply)  # the system-written "why this suggestion" line
    checks = []
    for sentence in split_sentences(body):
        cited = tuple(dict.fromkeys(CITATION_RE.findall(sentence)))
        status: Status
        if not cited:
            status = "no_citation" if detector.is_claim(sentence) else "non_factual"
        elif any(pid not in passages for pid in cited):
            status = "unknown_passage"
        elif not detector.is_claim(sentence):
            status = "non_factual"
        else:
            premise = "\n".join(passages[pid] for pid in cited)
            # Judges see the bare claim: citation tags confuse NLI models.
            claim = re.sub(r"\s+([.,;:!?])", r"\1", CITATION_RE.sub("", sentence)).strip()
            claim = _ATTRIBUTION_RE.sub("", claim).strip()
            status = "ok" if judge.entails(premise, claim) else "not_entailed"
        checks.append(SentenceCheck(sentence, cited, status))
    return GroundingReport(tuple(checks))


@dataclass(frozen=True)
class GroundedReply:
    text: str
    report: GroundingReport
    attempts: int
    escalate: bool
    draft: str = ""  # the last generated reply (kept so it can be shown, labelled unverified)


def grounded_generate(
    generate: Callable[[str | None], str],
    passages: Mapping[str, str],
    judge: EntailmentJudge,
    *,
    max_regenerations: int,
    uncertain_reply: str,
    detector: ClaimDetector | None = None,
    registry: PromptRegistry | None = None,
) -> GroundedReply:
    """``generate(feedback)`` produces a reply; feedback is None on the first attempt."""
    registry = registry or default_registry()
    feedback: str | None = None
    report = GroundingReport(())
    reply = ""
    for attempt in range(1, max_regenerations + 2):
        reply = generate(feedback)
        report = check_grounding(reply, passages, judge, detector)
        if report.ok:
            return GroundedReply(reply, report, attempt, escalate=False)
        feedback = registry.get("rag/regenerate_feedback").render(problems=report.problems()).user
    return GroundedReply(uncertain_reply, report, max_regenerations + 1, escalate=True, draft=reply)


def record_grounding_escalation(
    session_factory: StoreFactory,
    learner_id: str,
    session_id: str | None,
    report: GroundingReport,
) -> int:
    with session_factory.begin() as db:
        esc = m.Escalation(
            learner_id=learner_id,
            session_id=session_id,
            reason="grounding_failure",
            message="Reply failed the grounding check twice:\n" + report.problems(),
        )
        db.add(esc)
        db.flush()
        return esc.id
