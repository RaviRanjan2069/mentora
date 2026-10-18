"""Offline template tutor: picks the notes on the current topic, reacts to what was asked,
and only states facts as exact, cited sentences from the notes (so grounding can pass)."""

from __future__ import annotations

from mentora.llm.backends.offline import OfflineLLM
from mentora.llm.types import LLMRequest, Message
from mentora.rag.grounding import LexicalEntailmentJudge, check_grounding
from mentora.rag.text import CITATION_RE, split_sentences

STRINGS = (
    "A string is an immutable sequence of characters. Immutable means that you cannot change "
    "a string in place; operations such as `upper()` return a new string. `s[::-1]` reverses s."
)
DICTS = (
    "A dictionary maps keys to values. `d[key]` raises a KeyError if the key is missing. "
    "`d.get(key, default)` returns the default instead; without a default it returns None."
)
PASSAGES = {"c-week3-strings-p001": STRINGS, "c-week5-dicts-p001": DICTS}


def _prompt(move: str, message: str) -> LLMRequest:
    passages = "\n\n".join(f"[{pid}] {text}" for pid, text in PASSAGES.items())
    user = (
        f"Course passages (cite a passage by its id):\n{passages}\n\nCurrent task:\n"
        'Question: What is printed?\ns = "cherry"\ns.upper()\nprint(s)\n(A) CHERRY\n(B) None\n'
        "Target concept: Strings\n\nThe learner's latest message is below.\n"
        f"<learner_message>\n{message}\n</learner_message>\n"
    )
    return LLMRequest(
        system="",
        messages=(Message("user", user),),
        max_tokens=100,
        prompt_id=f"agents/turn:ContentTutor.{move}.Socratic",
    )


def _reply(move: str, message: str) -> str:
    return OfflineLLM().complete(_prompt(move, message)).text


def test_hint_uses_the_topic_notes_and_passes_grounding() -> None:
    reply = _reply("graded_hint", "Can I get a hint?")
    assert set(CITATION_RE.findall(reply)) == {"c-week3-strings-p001"}  # not the dicts notes
    assert check_grounding(reply, PASSAGES, LexicalEntailmentJudge(0.6)).ok


def test_explain_request_quotes_two_sentences_and_example_prefers_code() -> None:
    assert len(CITATION_RE.findall(_reply("graded_hint", "Can you explain that again?"))) == 2
    example = _reply("graded_hint", "Can you show me a similar example?")
    assert "`" in example and len(CITATION_RE.findall(example)) == 1
    explained = _reply("concept_explanation", "I don't understand")
    assert check_grounding(explained, PASSAGES, LexicalEntailmentJudge(0.6)).ok


def test_code_subscripts_are_not_citations_and_inline_code_starts_a_sentence() -> None:
    assert CITATION_RE.findall("see d[key], lst[0], lst[-1] and [c-week5-dicts-p001]") == [
        "c-week5-dicts-p001"
    ]
    assert split_sentences("Copy with `a[:]`. `lst.sort()` returns None.") == [
        "Copy with `a[:]`.",
        "`lst.sort()` returns None.",
    ]
