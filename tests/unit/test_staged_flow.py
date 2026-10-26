"""Pure staged Telegram flow validation and stage-specific keyboards."""

from datetime import UTC, datetime

import pytest

from coaching_inquiry_engine.agent.config import CONVERSATION_TEXTS
from coaching_inquiry_engine.domain.exam_menu import load_exam_menu
from coaching_inquiry_engine.domain.flow import (
    EligibilityStatus,
    ExpectedInput,
    FlowContext,
    FlowStage,
    buttons_for_stage,
    evaluate_eligibility,
    expected_input,
    transition,
)

_NOW = datetime(2026, 10, 26, tzinfo=UTC)
_MENU = load_exam_menu("data/exams.yaml")
_QUALIFICATIONS = ("Class 10", "Class 12", "Graduate")


@pytest.mark.parametrize("value", ["Ankush4", "😊", "A"])
def test_name_stage_rejects_digits_emoji_and_single_character(value: str) -> None:
    result = transition(
        FlowContext(stage=FlowStage.name),
        value=value,
        now=_NOW,
        qualification_options=_QUALIFICATIONS,
        exam_menu=_MENU,
    )
    assert result.retry is True
    assert result.text_key == "name_retry"
    assert result.context.stage is FlowStage.name


@pytest.mark.parametrize("value", ["Ankush", "O'Neil", "A. Sharma", "अंकुश"])
def test_name_stage_accepts_unicode_letters_and_allowed_punctuation(value: str) -> None:
    result = transition(
        FlowContext(stage=FlowStage.name),
        value=value,
        now=_NOW,
        qualification_options=_QUALIFICATIONS,
        exam_menu=_MENU,
    )
    assert result.context.name == value
    assert result.context.stage is FlowStage.age
    assert result.text_key == "age_prompt"


@pytest.mark.parametrize("value", ["13", "71", "abc"])
def test_age_stage_rejects_values_outside_14_to_70_or_non_numeric(value: str) -> None:
    result = transition(
        FlowContext(stage=FlowStage.age),
        value=value,
        now=_NOW,
        qualification_options=_QUALIFICATIONS,
        exam_menu=_MENU,
    )
    assert result.retry is True
    assert result.text_key == "age_retry"


@pytest.mark.parametrize("value", ["14", "70"])
def test_age_stage_accepts_inclusive_bounds(value: str) -> None:
    result = transition(
        FlowContext(stage=FlowStage.age),
        value=value,
        now=_NOW,
        qualification_options=_QUALIFICATIONS,
        exam_menu=_MENU,
    )
    assert result.context.age_years == int(value)
    assert result.context.stage is FlowStage.qualification


def test_eligibility_without_verified_rule_requires_confirmation() -> None:
    assert (
        evaluate_eligibility(22, "Graduate", (), _QUALIFICATIONS)
        is EligibilityStatus.to_confirm
    )


def test_eligibility_compares_only_explicit_verified_summary_rules() -> None:
    summary = ("Age 18-30; eligible qualifications are Class 12 and Graduate.",)
    assert (
        evaluate_eligibility(22, "Graduate", summary, _QUALIFICATIONS)
        is EligibilityStatus.eligible
    )
    assert (
        evaluate_eligibility(31, "Graduate", summary, _QUALIFICATIONS)
        is EligibilityStatus.not_eligible
    )


def test_buttons_match_only_the_current_stage_and_date_of_birth_is_never_asked() -> (
    None
):
    flow = FlowContext(stage=FlowStage.exam_category)
    buttons = buttons_for_stage(
        flow,
        qualification_options=_QUALIFICATIONS,
        exam_menu=_MENU,
    )
    assert buttons
    assert all(button.action_id.startswith("category:") for button in buttons)
    assert expected_input(FlowStage.name) is ExpectedInput.letters
    assert "date of birth" not in " ".join(CONVERSATION_TEXTS.values()).casefold()
