"""Classify what a learner message literally asks for. The category (never the text)
is used by the rule policy and the reliance profile."""

from __future__ import annotations

import re
from typing import Literal

Request = Literal[
    "answer", "hint", "example", "practice", "explanation", "plan", "question", "none"
]

_PATTERNS: list[tuple[Request, re.Pattern[str]]] = [
    (
        "answer",
        re.compile(
            r"\b(just )?(tell|give|show) me the (answer|solution|code)|"
            r"what('?s| is) the (answer|solution)|which (option|one) is (right|correct)|"
            r"\bsolve (it|this) for me|do (it|this) for me",
            re.IGNORECASE,
        ),
    ),
    (
        "practice",
        re.compile(
            r"\bpractice (question|problem|item|exercise)\b|"
            r"\b(give|ask) me (a |another |one more )?(question|exercise|problem)\b|\bquiz me\b",
            re.IGNORECASE,
        ),
    ),
    ("hint", re.compile(r"\b(a |another )?hint\b|\bclue\b|\bnudge\b|\bstuck\b", re.IGNORECASE)),
    (
        "example",
        re.compile(r"\b(similar|another|an|worked) example\b|\bshow me (one|how)\b", re.IGNORECASE),
    ),
    (
        "explanation",
        re.compile(
            r"\b(explain|what does .+ mean|what is (a|an|the)\b|why (does|is|do)|"
            r"how does|don'?t (get|understand)|confused)",
            re.IGNORECASE,
        ),
    ),
    (
        "plan",
        re.compile(
            r"\b(plan|goal|schedule|where (do|should) i start|what should i do)\b", re.IGNORECASE
        ),
    ),
]


# A question typed without a question mark ("what is a decorator").
_QUESTION_START = re.compile(
    r"\s*(what|why|how|when|where|who|whom|which|can|could|would|is|are|does|do|did|should|"
    r"will|tell me|define|describe|compare|difference between)(?![a-z])",
    re.IGNORECASE,
)


def classify_request(text: str | None) -> Request:
    if not text or not text.strip():
        return "none"
    for kind, pattern in _PATTERNS:
        if pattern.search(text):
            return kind
    if text.strip().endswith("?") or _QUESTION_START.match(text):
        return "question"
    return "none"
