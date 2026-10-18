from __future__ import annotations

import pytest
from pydantic import ValidationError

from mentora.logging_xapi.statements import (
    EXT_TUTOR_ACTION,
    ActionRef,
    FilterOutcome,
    Statement,
    TutorActionExtension,
    learner_message,
    tutor_action,
)
from mentora.privacy import pseudonymize

HINT = ActionRef(agent="ContentTutor", move="graded_hint", style="Socratic")


def _ext(**overrides: object) -> TutorActionExtension:
    fields: dict[str, object] = {
        "policy_version": "rule-v1",
        "action": HINT,
        "propensity": 0.7,
        "filter_outcome": FilterOutcome(feasible_action_ids=[HINT.id, "WAIT"]),
    }
    fields.update(overrides)
    return TutorActionExtension.model_validate(fields)


def test_action_ids() -> None:
    assert HINT.id == "ContentTutor.graded_hint.Socratic"
    assert ActionRef(move="WAIT").id == "WAIT"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"move": "WAIT", "agent": "Planner"},
        {"move": "ESCALATE", "style": "Socratic"},
        {"move": "graded_hint", "agent": "ContentTutor"},
        {"move": "graded_hint", "style": "Socratic"},
    ],
)
def test_malformed_actions_rejected(kwargs: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ActionRef.model_validate(kwargs)


@pytest.mark.parametrize("p", [0.0, -0.1, 1.01])
def test_propensity_must_be_in_unit_interval(p: float) -> None:
    with pytest.raises(ValidationError):
        _ext(propensity=p)


def test_action_outside_feasible_set_rejected() -> None:
    with pytest.raises(ValidationError, match="outside the feasible set"):
        _ext(filter_outcome=FilterOutcome(feasible_action_ids=["WAIT"]))


def test_escalate_requires_flag() -> None:
    esc = ActionRef(move="ESCALATE")
    outcome = FilterOutcome(feasible_action_ids=["ESCALATE"])
    with pytest.raises(ValidationError):
        _ext(action=esc, filter_outcome=outcome, escalated=False)
    assert _ext(action=esc, filter_outcome=outcome, escalated=True).escalated


def test_tutor_statement_roundtrips_through_json() -> None:
    ext = _ext(retrieved_passage_ids=["p-001", "p-007"], prompt_version="content/v1")
    st = tutor_action("lrn_x", "sess-1", 3, ext, "What do you notice about line 2?")
    payload = st.to_json_dict()
    assert "object" in payload and EXT_TUTOR_ACTION in payload["context"]["extensions"]
    back = Statement.model_validate(payload)
    assert back == st
    assert back.tutor_action == ext
    assert back.turn == 3


def test_learner_statement_has_no_tutor_extension() -> None:
    st = learner_message("lrn_x", "sess-1", 1, "I want to learn recursion")
    assert st.tutor_action is None
    assert st.result is not None and st.result.response == "I want to learn recursion"


def test_pseudonyms_are_stable_and_salted() -> None:
    assert pseudonymize("moodle-42", "a") == pseudonymize("moodle-42", "a")
    assert pseudonymize("moodle-42", "a") != pseudonymize("moodle-42", "b")
    assert "moodle-42" not in pseudonymize("moodle-42", "a")
