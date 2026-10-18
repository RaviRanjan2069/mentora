"""M2 'done when': the grounding check catches an unsupported sentence."""

from __future__ import annotations

from mentora.db import StoreFactory
from mentora.db import models as m
from mentora.rag.grounding import (
    HeuristicClaimDetector,
    LexicalEntailmentJudge,
    check_grounding,
    grounded_generate,
    record_grounding_escalation,
)

PASSAGES = {
    "syn-w1-p03": "The // operator performs floor division, so 7 // 2 gives 3.",
    "syn-w3-p02": "range(5) gives 0, 1, 2, 3 and 4: it starts at 0 and stops before 5.",
}
JUDGE = LexicalEntailmentJudge(threshold=0.6)
UNCERTAIN = "I am not certain about this; I have asked your teacher."


def _statuses(reply: str) -> list[str]:
    return [c.status for c in check_grounding(reply, PASSAGES, JUDGE).checks]


def test_supported_reply_passes() -> None:
    reply = (
        "The // operator performs floor division [syn-w1-p03]. "
        "What do you think 9 // 2 gives? "
        "Why this suggestion: you asked about an operator from week 1."
    )
    report = check_grounding(reply, PASSAGES, JUDGE)
    assert report.ok
    assert [c.status for c in report.checks] == ["ok", "non_factual"]  # why-line excluded


def test_uncited_claim_is_caught() -> None:
    reply = (
        "The // operator performs floor division [syn-w1-p03]. "
        "Python was first released in 1991 by Guido van Rossum."
    )
    report = check_grounding(reply, PASSAGES, JUDGE)
    assert not report.ok
    assert report.failures[0].status == "no_citation"
    assert "1991" in report.failures[0].sentence


def test_cited_but_unsupported_claim_is_caught() -> None:
    assert _statuses("The // operator always returns a float value [syn-w1-p03].") == [
        "not_entailed"
    ]


def test_changed_number_is_caught() -> None:
    assert _statuses("Floor division gives 4 for 7 // 2 [syn-w1-p03].") == ["not_entailed"]


def test_negation_flip_is_caught() -> None:
    assert _statuses("range(5) does not start at 0 and stops before 5 [syn-w3-p02].") == [
        "not_entailed"
    ]


def test_unknown_passage_id_is_caught() -> None:
    assert _statuses("Loops repeat code until a condition fails [syn-w9-p99].") == [
        "unknown_passage"
    ]


def test_questions_and_instructions_are_not_claims() -> None:
    detector = HeuristicClaimDetector()
    for s in [
        "What does range(5) give?",
        "Try writing the loop yourself first.",
        "Let's check your plan.",
        "You set a goal to finish week 3.",
        "Great work.",
    ]:
        assert not detector.is_claim(s), s
    assert detector.is_claim("A while loop checks its condition before every iteration.")


def test_regenerates_once_then_passes() -> None:
    replies = iter(
        [
            "Floor division always rounds up.",  # unsupported, no citation
            "The // operator performs floor division [syn-w1-p03].",
        ]
    )
    feedback_seen: list[str | None] = []

    def generate(feedback: str | None) -> str:
        feedback_seen.append(feedback)
        return next(replies)

    out = grounded_generate(
        generate, PASSAGES, JUDGE, max_regenerations=1, uncertain_reply=UNCERTAIN
    )
    assert out.text.startswith("The // operator") and out.attempts == 2 and not out.escalate
    assert feedback_seen[0] is None
    assert feedback_seen[1] is not None and "cites no passage" in feedback_seen[1]


def test_fails_twice_then_uncertain_reply_and_escalation(
    session_factory: StoreFactory, seeded: dict[str, str]
) -> None:
    out = grounded_generate(
        lambda _fb: "Python was invented in 1850 by a snake.",
        PASSAGES,
        JUDGE,
        max_regenerations=1,
        uncertain_reply=UNCERTAIN,
    )
    assert out.escalate and out.text == UNCERTAIN and out.attempts == 2

    esc_id = record_grounding_escalation(
        session_factory, seeded["learner_id"], seeded["session_id"], out.report
    )
    with session_factory() as db:
        esc = db.get(m.Escalation, esc_id)
        assert esc is not None
    assert esc.reason == "grounding_failure" and esc.status == "open"
    assert esc.message is not None and "1850" in esc.message


def test_faithfulness_metric() -> None:
    report = check_grounding(
        "The // operator performs floor division [syn-w1-p03]. Python is very old.",
        PASSAGES,
        JUDGE,
    )
    assert report.faithfulness == 0.5
    assert check_grounding("What next?", PASSAGES, JUDGE).faithfulness is None
