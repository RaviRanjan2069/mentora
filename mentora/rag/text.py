"""Small text helpers shared by ingest, retrieval and grounding."""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"\w+|[^\w\s]")
_WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
# A new sentence starts with a capital, a digit, or inline code (`x = 1` ...).
_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9]|`)")
# Passage ids always contain a hyphen (course-file-p001), so code such as d[key] or lst[0]
# is never mistaken for a citation.
CITATION_RE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)+)\]")

STOPWORDS = frozenset(
    """a about above after again all also am an and any are as at be because been before
    being below between both but by can could did do does doing down during each few for
    from further had has have having he her here hers him his how i if in into is it its
    itself just let lets me more most my no nor not of off on once only or other our ours
    out over own same she should so some such than that the their theirs them then there
    these they this those through to too under until up very was we were what when where
    which while who whom why will with would you your yours""".split()
)
NEGATIONS = frozenset(
    {"not", "no", "never", "cannot", "can't", "don't", "doesn't", "isn't", "won't"}
)


def count_tokens(text: str) -> int:
    """Approximate subword-token count (words and punctuation). See docs/decisions.md D13."""
    return len(_TOKEN_RE.findall(text))


def words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def content_words(text: str) -> list[str]:
    return [w for w in words(CITATION_RE.sub(" ", text)) if w not in STOPWORDS]


def split_sentences(text: str) -> list[str]:
    out: list[str] = []
    for para in re.split(r"\n\s*\n|\n(?=\s*[-*] )", text):
        para = " ".join(para.split())
        if para:
            out.extend(s.strip() for s in _SENT_RE.split(para) if s.strip())
    return out


def slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-") or "doc"
