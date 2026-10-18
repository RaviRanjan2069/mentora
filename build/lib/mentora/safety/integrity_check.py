"""Output-side academic-integrity check (design rule 6): a reply about a graded item must
not reveal the answer or contain a full solution."""

from __future__ import annotations

import re
from dataclasses import dataclass

_GIVEAWAY_RE = re.compile(
    r"\b(the (correct |right |final )?answer is|correct (option|choice|answer) is|"
    r"here(?:'s| is) the (full |complete )?(solution|answer|code)|"
    r"the solution is|you should (choose|pick|select) (option )?[a-e]\b|"
    r"just (write|type|enter|submit))",
    re.IGNORECASE,
)
_CODE_BLOCK_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
_SHORT_KEYS = frozenset({"yes", "no", "true", "false"})


@dataclass(frozen=True)
class ItemView:
    """What the safety layer knows about the current task. ``answer_key`` is never put in
    an LLM prompt; it is used here only to check outputs."""

    text: str
    graded: bool
    answer_key: str | None = None
    item_type: str = "mcq"


@dataclass(frozen=True)
class IntegrityResult:
    ok: bool
    reasons: tuple[str, ...] = ()


def _normalize(s: str) -> str:
    return " ".join(s.lower().split())


def _reveals_key(text: str, item: ItemView) -> bool:
    key = (item.answer_key or "").strip()
    if not key:
        return False
    if item.item_type == "mcq" and re.fullmatch(r"[A-Ea-e]", key):
        letter = key.upper()
        # "option B", "(B) is", "the answer to the quiz is B", "pick B": an answer word
        # followed within a short span by the key letter as a standalone capital or "(B)".
        near_answer_word = (
            r"(?i:\b(answers?|options?|choices?|correct|right|pick|choose|select|go with)\b)"
            rf"[^.?!\n]{{0,30}}(?<![\w(])\(?{letter}\)?(?![\w])"
        )
        return any(
            re.search(near_answer_word, s) or re.search(rf"\({letter}\)\s*is\b", s)
            for s in _statements(text)
        )
    norm_key, norm_text = _normalize(key), _normalize(text)
    if re.fullmatch(r"-?\d+(\.\d+)?", norm_key):
        return bool(re.search(rf"(?<![\w.]){re.escape(norm_key)}(?![\w.])", norm_text))
    if norm_key in _SHORT_KEYS:
        # A yes/no-style key leaks when it is stated outside a question.
        return any(re.search(rf"\b{norm_key}\b", s, re.IGNORECASE) for s in _statements(text))
    return len(norm_key) >= 3 and norm_key in norm_text


def _statements(text: str) -> list[str]:
    """Sentences that are not questions (a question naming an option does not reveal it)."""
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if not s.strip().endswith("?")]


def _code_lines(text: str) -> int:
    blocks = _CODE_BLOCK_RE.findall(text)
    return max((len([ln for ln in b.splitlines() if ln.strip()]) for b in blocks), default=0)


def integrity_check(text: str, item: ItemView | None, *, max_code_lines: int) -> IntegrityResult:
    """Only graded items are checked; ungraded practice may show worked solutions."""
    if item is None or not item.graded:
        return IntegrityResult(True)
    reasons = []
    if _reveals_key(text, item):
        reasons.append("reveals the answer key")
    if _GIVEAWAY_RE.search(text):
        reasons.append("states or hands over the answer")
    if _code_lines(text) > max_code_lines:
        reasons.append(f"contains a code block longer than {max_code_lines} lines")
    return IntegrityResult(not reasons, tuple(reasons))
