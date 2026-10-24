"""Post-validation rules: one passing and one failing case each."""

from __future__ import annotations

import pytest

from coaching_inquiry_engine.domain import (
    AgentDecision,
    DecisionRejectedError,
    NextAction,
    check_decision,
)
from coaching_inquiry_engine.domain.llm_checks import (
    check_booking_choice,
    check_credential_request,
    check_forbidden_claims,
    check_unapproved_quantities,
    reply_requests_personal_data,
)

_BASE = {
    "reply_text": "Which stage of preparation are you in?",
    "field_updates": {},
    "booking_choice_index": None,
    "escalation_reason": None,
    "prompt_version": "upsc_v0.2",
}


def _decision(**overrides: object) -> AgentDecision:
    payload = {**_BASE, "next_action": "ask_field", **overrides}
    return AgentDecision.model_validate(payload)


def test_booking_choice_index_in_offered_options_passes() -> None:
    decision = _decision(
        next_action=NextAction.booking_choice,
        booking_choice_index=1,
        reply_text="Booking the middle offered slot.",
    )
    check_booking_choice(decision, frozenset({0, 1, 2}))


def test_booking_choice_index_missing_from_offers_fails() -> None:
    decision = _decision(
        next_action=NextAction.booking_choice,
        booking_choice_index=2,
        reply_text="Booking a listed slot.",
    )
    with pytest.raises(DecisionRejectedError):
        check_booking_choice(decision, frozenset({0, 1}))


def test_reply_without_quantities_passes() -> None:
    check_unapproved_quantities("Which timeline fits you best?", ())


def test_reply_with_unapproved_time_fails() -> None:
    with pytest.raises(DecisionRejectedError):
        check_unapproved_quantities("Please join at 4:30 pm", ())


def test_reply_repeating_offered_time_passes() -> None:
    check_unapproved_quantities(
        "Saturday 4:30 pm is still open.",
        ("Saturday 4:30 pm",),
    )


def test_reply_with_unapproved_date_fails() -> None:
    with pytest.raises(DecisionRejectedError):
        check_unapproved_quantities("The batch starts on 24/10/2026", ())


def test_reply_with_unapproved_price_fails() -> None:
    with pytest.raises(DecisionRejectedError):
        check_unapproved_quantities("Fees are Rs 5000 this week", ())


def test_reply_with_unapproved_percent_fails() -> None:
    with pytest.raises(DecisionRejectedError):
        check_unapproved_quantities("You get 20% off if you join now", ())


def test_reply_without_credentials_passes() -> None:
    check_credential_request("What should we call you?")


def test_reply_requesting_otp_fails() -> None:
    with pytest.raises(DecisionRejectedError):
        check_credential_request("Please share the OTP sent to you")


def test_reply_without_forbidden_claims_passes() -> None:
    check_forbidden_claims("A counsellor can discuss expected outcomes.")


def test_reply_with_guaranteed_fails() -> None:
    with pytest.raises(DecisionRejectedError):
        check_forbidden_claims("Selection is guaranteed if you join")


def test_check_decision_accepts_a_clean_ask() -> None:
    check_decision(_decision(), offered_indices=frozenset())


def test_reply_requesting_date_of_birth_is_rejected() -> None:
    reply = "Can you tell me your date of birth?"

    assert reply_requests_personal_data(reply)
    with pytest.raises(DecisionRejectedError):
        check_decision(
            _decision(reply_text=reply),
            offered_indices=frozenset(),
        )


def test_reply_asking_about_batch_passes_personal_data_check() -> None:
    assert not reply_requests_personal_data("Which batch are you interested in?")
