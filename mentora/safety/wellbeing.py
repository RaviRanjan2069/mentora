"""Deterministic distress detection (design rule 7): any match routes the turn to
ESCALATE and shows support resources. No LLM is involved."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from mentora.config.settings import SafetySettings

LEXICON_FILE = Path(__file__).with_name("distress_lexicon.yaml")
Tier = Literal["crisis", "distress"]
_NEGATION_RE = re.compile(r"\b(not|never|no longer)\s+(\w+\s+)?$", re.IGNORECASE)


@dataclass(frozen=True)
class DistressResult:
    detected: bool
    tier: Tier | None = None
    matches: tuple[str, ...] = ()


@lru_cache(maxsize=4)
def _patterns(path: Path = LEXICON_FILE) -> dict[Tier, list[re.Pattern[str]]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        tier: [re.compile(rf"\b(?:{p})\b", re.IGNORECASE) for p in raw.get(tier, [])]
        for tier in ("crisis", "distress")
    }


def detect_distress(text: str | None, lexicon: Path = LEXICON_FILE) -> DistressResult:
    if not text:
        return DistressResult(False)
    normalized = text.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'")
    for tier in ("crisis", "distress"):
        hits = []
        for pattern in _patterns(lexicon)[tier]:
            for match in pattern.finditer(normalized):
                # "I'm not overwhelmed" is not distress; crisis terms ignore negation.
                if tier == "distress" and _NEGATION_RE.search(normalized[: match.start()]):
                    continue
                hits.append(match.group(0))
        if hits:
            return DistressResult(True, tier, tuple(hits))
    return DistressResult(False)


def support_message(settings: SafetySettings) -> str:
    lines = "\n".join(f"- {r}" for r in settings.support_resources)
    return f"{settings.distress_reply}\n{lines}"
