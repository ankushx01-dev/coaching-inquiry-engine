"""Counselling request flow controls and safe confirmations."""

from datetime import UTC, datetime

from coaching_inquiry_engine.agent.config import CONVERSATION_TEXTS, TEXT_REVIEW_STATUS
from coaching_inquiry_engine.domain.exam_menu import load_exam_menu
from coaching_inquiry_engine.domain.flow import (
    EligibilityStatus,
    FlowContext,
    FlowStage,
    buttons_for_stage,
    transition,
)

_NOW = datetime(2026, 10, 26, tzinfo=UTC)
_MENU = load_exam_menu("data/exams.yaml")
_QUALIFICATIONS = ("Class 10", "Class 12", "Graduate")


def _transition(context: FlowContext, value: str):
    return transition(
        context,
        value=value,
        now=_NOW,
        qualification_options=_QUALIFICATIONS,
        exam_menu=_MENU,
    )


def _complete(**updates: object) -> FlowContext:
    values: dict[str, object] = {
        "stage": FlowStage.course_options,
        "goal": "Prepare for civil services",
        "name": "Ankush Rana",
        "age_years": 22,
        "qualification": "Graduate",
        "exam_category": "civil_services",
        "exam_id": "upsc_cse",
        "eligibility_status": EligibilityStatus.eligible,
    }
    values.update(updates)
    return FlowContext.model_validate(values)


def test_counsellor_action_starts_contact_only_after_required_fields() -> None:
    result = _transition(_complete(), "counselling:start")
    assert result.context.stage is FlowStage.contact
    assert result.text_key == "contact_ask"


def test_missing_field_is_requested_in_workflow_order() -> None:
    context = _complete(goal=None, name=None)
    result = _transition(context, "counselling:start")
    assert result.context.stage is FlowStage.goal
    assert result.context.counselling_resume is True
    assert result.text_key == "goal_prompt"


def test_resumed_flow_does_not_repeat_valid_fields() -> None:
    context = _complete(
        stage=FlowStage.goal,
        goal=None,
        counselling_resume=True,
        contact_method="telegram",
    )
    result = _transition(context, "Prepare for civil services")
    assert result.context.stage is FlowStage.counselling_review
    assert result.context.name == "Ankush Rana"
    assert result.text_key == "counselling_review_prompt"


def test_contact_manual_and_telegram_paths_reach_safe_review() -> None:
    contact = _transition(_complete(stage=FlowStage.contact), "contact:manual")
    assert contact.context.stage is FlowStage.contact_manual
    manual = _transition(contact.context, "contact:manual_saved")
    assert manual.context.contact_method == "phone"
    assert manual.context.stage is FlowStage.counselling_review

    telegram = _transition(
        _complete(stage=FlowStage.contact), "contact:here"
    )
    assert telegram.context.contact_method == "telegram"
    assert telegram.context.stage is FlowStage.counselling_review


def test_invalid_contact_and_confirmation_in_the_wrong_stage_retry_safely() -> None:
    contact = _transition(_complete(stage=FlowStage.contact), "contact:invalid")
    assert contact.context.stage is FlowStage.contact
    assert contact.text_key == "contact_retry"

    invalid_confirm = _transition(
        _complete(stage=FlowStage.contact), "counselling:confirm"
    )
    assert invalid_confirm.action == "retry"
    assert invalid_confirm.text_key == "contact_retry"


def test_review_requires_second_confirmation_and_is_idempotent_in_flow() -> None:
    context = _complete(
        stage=FlowStage.counselling_review,
        contact_method="telegram",
    )
    confirm = _transition(context, "counselling:confirm")
    assert confirm.action == "create_counselling_request"
    assert confirm.context.counselling_request_submitted is True
    duplicate = _transition(confirm.context, "counselling:start")
    assert duplicate.action == "already_submitted"
    assert buttons_for_stage(
        FlowContext(stage=FlowStage.request_received),
        qualification_options=_QUALIFICATIONS,
        exam_menu=_MENU,
    )[0].action_id == "nav:main"


def test_cancel_returns_to_courses_without_clearing_lead_information() -> None:
    context = _complete(
        stage=FlowStage.counselling_review,
        contact_method="telegram",
    )
    cancelled = _transition(context, "counselling:cancel")
    assert cancelled.context.stage is FlowStage.course_options
    assert cancelled.context.name == context.name
    assert cancelled.context.exam_id == context.exam_id
    assert cancelled.text_key == "counselling_cancelled"


def test_back_preserves_details_and_submitted_request_hides_duplicate_cta() -> None:
    context = _complete(stage=FlowStage.contact, counselling_resume=True)
    back = _transition(context, "contact:back")
    assert back.context.stage is FlowStage.course_options
    assert back.context.name == context.name
    assert back.context.counselling_resume is True

    submitted = _complete(counselling_request_submitted=True)
    buttons = buttons_for_stage(
        submitted,
        qualification_options=_QUALIFICATIONS,
        exam_menu=_MENU,
    )
    assert all(button.action_id != "counselling:start" for button in buttons)


def test_new_localization_keys_have_safe_copy_and_review_values() -> None:
    assert "response time" not in CONVERSATION_TEXTS[
        "counsellor_request_received"
    ].casefold()
    confirmation = CONVERSATION_TEXTS["counsellor_request_received"].format(
        first_name="Ankush"
    )
    assert confirmation == "Thanks, Ankush. Your counselling request has been received."
    assert "Rana" not in confirmation
    required = {
        "contact_ask",
        "contact_retry",
        "counsellor_request_received",
        "counselling_review_prompt",
    }
    assert required <= set(CONVERSATION_TEXTS)
    assert all("TO_APPROVE" not in TEXT_REVIEW_STATUS[key] for key in required)
