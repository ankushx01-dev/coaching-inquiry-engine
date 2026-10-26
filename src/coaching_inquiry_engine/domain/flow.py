"""Deterministic, framework-free staged conversation flow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from coaching_inquiry_engine.domain.exam_menu import ExamMenuFile
from coaching_inquiry_engine.domain.models import normalize_person_name
from coaching_inquiry_engine.domain.quick_replies import QuickReply


class FlowStage(StrEnum):
    consent = "consent"
    goal = "goal"
    name = "name"
    age = "age"
    qualification = "qualification"
    exam_category = "exam_category"
    exam = "exam"
    eligibility = "eligibility"
    course_options = "course_options"
    contact = "contact"
    contact_manual = "contact_manual"
    counselling_review = "counselling_review"
    request_received = "request_received"
    booking = "booking"
    closed = "closed"


class ExpectedInput(StrEnum):
    button = "button"
    number = "number"
    letters = "letters"
    free_text = "free text"


class EligibilityStatus(StrEnum):
    eligible = "eligible"
    not_eligible = "not_eligible"
    to_confirm = "to_confirm"


class FlowContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: FlowStage = FlowStage.consent
    goal: str | None = None
    name: str | None = None
    age_years: int | None = None
    qualification: str | None = None
    exam_category: str | None = None
    exam_id: str | None = None
    eligibility_status: EligibilityStatus | None = None
    contact_method: Literal["phone", "telegram"] | None = None
    counselling_resume: bool = False
    counselling_request_submitted: bool = False
    category_page: int = 0
    consent_notice_sent: bool = False
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FlowTransition:
    context: FlowContext
    action: str
    text_key: str | None = None
    text: str | None = None
    retry: bool = False


def expected_input(stage: FlowStage) -> ExpectedInput:
    """Return the single accepted input kind for a flow stage."""
    return {
        FlowStage.consent: ExpectedInput.button,
        FlowStage.goal: ExpectedInput.free_text,
        FlowStage.name: ExpectedInput.letters,
        FlowStage.age: ExpectedInput.number,
        FlowStage.qualification: ExpectedInput.button,
        FlowStage.exam_category: ExpectedInput.button,
        FlowStage.exam: ExpectedInput.button,
        FlowStage.eligibility: ExpectedInput.button,
        FlowStage.course_options: ExpectedInput.button,
        FlowStage.contact: ExpectedInput.button,
        FlowStage.contact_manual: ExpectedInput.free_text,
        FlowStage.counselling_review: ExpectedInput.button,
        FlowStage.request_received: ExpectedInput.button,
        FlowStage.booking: ExpectedInput.button,
        FlowStage.closed: ExpectedInput.button,
    }[stage]


def transition(
    context: FlowContext,
    *,
    value: str,
    now: datetime,
    qualification_options: tuple[str, ...],
    exam_menu: ExamMenuFile,
) -> FlowTransition:
    """Apply one stage input without I/O, using the supplied transition time."""
    stage = context.stage
    if stage is FlowStage.consent:
        if value != "consent:agree":
            return _retry(context, "consent")
        return _next(context, FlowStage.goal, "goal_prompt", now)

    if stage is FlowStage.goal:
        goal = value.strip()
        if not goal or len(goal) > 200 or _looks_like_action(goal):
            return _retry(context, "goal_prompt")
        updated = context.model_copy(update={"goal": goal})
        return _continue_counselling_resume(
            updated, FlowStage.name, "name_prompt", now
        )

    if stage is FlowStage.name:
        name_input = re.sub(
            r"^(?:my name is|i am|i'm)\s+", "", value.strip(), flags=re.IGNORECASE
        )
        try:
            name = normalize_person_name(name_input)
        except ValueError:
            return _retry(context, "name_retry")
        if len(name) < 2:
            return _retry(context, "name_retry")
        updated = context.model_copy(update={"name": name})
        return _continue_counselling_resume(updated, FlowStage.age, "age_prompt", now)

    if stage is FlowStage.age:
        age = _parse_age(value)
        if age is None:
            return _retry(context, "age_retry")
        updated = context.model_copy(update={"age_years": age})
        return _continue_counselling_resume(
            updated, FlowStage.qualification, "qualification_prompt", now
        )

    if stage is FlowStage.qualification:
        index = _action_index(value, "qualification")
        if index is None or index >= len(qualification_options):
            return _retry(context, "qualification_prompt")
        updated = context.model_copy(
            update={"qualification": qualification_options[index]}
        )
        return _continue_counselling_resume(
            updated, FlowStage.exam_category, "category_menu_intro", now
        )

    if stage is FlowStage.exam_category:
        if value == "category:more":
            updated = context.model_copy(
                update={"category_page": context.category_page + 1}
            )
            return FlowTransition(updated, action="show_buttons")
        if value == "category:back":
            updated = context.model_copy(
                update={"category_page": max(0, context.category_page - 1)}
            )
            return FlowTransition(updated, action="show_buttons")
        category_id = value.removeprefix("category:")
        if not value.startswith("category:") or not any(
            category.category_id == category_id for category in exam_menu.categories
        ):
            return _retry(context, "category_menu_intro")
        updated = context.model_copy(
            update={
                "exam_category": category_id,
                "exam_id": None,
                "category_page": 0,
            }
        )
        return _continue_counselling_resume(
            updated, FlowStage.exam, "exam_menu_intro", now
        )

    if stage is FlowStage.exam:
        if value == "exam:back":
            return _next(context, FlowStage.exam_category, "category_menu_intro", now)
        exam_id = value.removeprefix("exam:")
        exam = next(
            (
                item
                for item in exam_menu.exams
                if item.exam_id == exam_id
                and item.category == context.exam_category
                and item.status == "ACTIVE"
            ),
            None,
        )
        if exam is None:
            return _retry(context, "exam_menu_intro")
        updated = context.model_copy(
            update={"exam_id": exam.exam_id, "eligibility_status": None}
        )
        return _continue_counselling_resume(
            updated, FlowStage.eligibility, "eligibility_prompt", now
        )

    if stage is FlowStage.eligibility:
        if value == "eligibility:check":
            return FlowTransition(
                context.model_copy(
                    update={"stage": FlowStage.course_options, "updated_at": now}
                ),
                action="check_eligibility",
            )
        if value == "flow:courses":
            return _next(
                context, FlowStage.course_options, "course_options_prompt", now
            )
        return _retry(context, "eligibility_prompt")

    if stage is FlowStage.course_options:
        if value in {"course:batch_timings", "course:fees", "course:demo_class"}:
            return FlowTransition(
                context.model_copy(update={"updated_at": now}), action=value
            )
        if value == "booking:create":
            return _next(
                context,
                FlowStage.booking,
                "booking_prompt",
                now,
                action="create_offers",
            )
        if value in {"handoff:counsellor", "counselling:start"}:
            if context.counselling_request_submitted:
                return FlowTransition(context, action="already_submitted")
            missing = _next_counselling_field(context)
            if missing is not None:
                next_stage, key = missing
                updated = context.model_copy(
                    update={
                        "stage": next_stage,
                        "counselling_resume": True,
                        "updated_at": now,
                    }
                )
                return FlowTransition(updated, action="reply", text_key=key)
            if context.contact_method is not None:
                return _next(
                    context,
                    FlowStage.counselling_review,
                    "counselling_review_prompt",
                    now,
                )
            return _next(
                context, FlowStage.contact, "contact_ask", now
            )
        return _retry(context, "course_options_prompt")

    if stage is FlowStage.contact:
        if value == "contact:manual":
            return _next(
                context, FlowStage.contact_manual, "contact_phone_prompt", now
            )
        if value == "contact:back":
            return _next(
                context, FlowStage.course_options, "course_options_prompt", now
            )
        if value == "contact:here":
            return _contact_review(context, "telegram", now)
        if value == "contact:cancel" or value == "nav:main":
            return _cancel_counselling(context, now)
        if value in {"contact:shared", "contact:manual_saved"}:
            return _contact_review(context, "phone", now)
        return _retry(context, "contact_retry")

    if stage is FlowStage.contact_manual:
        if value == "contact:back":
            return _next(context, FlowStage.contact, "contact_ask", now)
        if value == "contact:here":
            return _contact_review(context, "telegram", now)
        if value == "contact:cancel" or value == "nav:main":
            return _cancel_counselling(context, now)
        if value in {"contact:manual_saved", "contact:shared"}:
            return _contact_review(context, "phone", now)
        if value == "contact:invalid":
            return _retry(context, "contact_retry")
        return _retry(context, "contact_retry")

    if stage is FlowStage.counselling_review:
        if value == "counselling:back":
            return _next(context, FlowStage.contact, "contact_ask", now)
        if value == "counselling:cancel" or value == "nav:main":
            return _cancel_counselling(context, now)
        if value != "counselling:confirm":
            return _retry(context, "counselling_review_prompt")
        missing = _next_counselling_field(context)
        if missing is not None:
            next_stage, key = missing
            updated = context.model_copy(
                update={
                    "stage": next_stage,
                    "counselling_resume": True,
                    "updated_at": now,
                }
            )
            return FlowTransition(updated, action="reply", text_key=key)
        if context.contact_method is None:
            return _next(context, FlowStage.contact, "contact_ask", now)
        updated = context.model_copy(
            update={
                "stage": FlowStage.course_options,
                "counselling_resume": False,
                "counselling_request_submitted": True,
                "updated_at": now,
            }
        )
        return FlowTransition(updated, action="create_counselling_request")

    if stage is FlowStage.request_received:
        if value == "nav:main":
            return _next(
                context,
                FlowStage.course_options,
                "course_options_prompt",
                now,
            )
        return _retry(context, "course_options_prompt")

    if stage is FlowStage.booking:
        if value == "booking:create":
            return FlowTransition(
                context.model_copy(update={"updated_at": now}), action="create_offers"
            )
        if value == "booking:back":
            return _next(
                context, FlowStage.course_options, "course_options_prompt", now
            )
        index = _action_index(value, "slot")
        if index is not None:
            return FlowTransition(
                context.model_copy(update={"updated_at": now}),
                action=f"book_offer:{index}",
            )
        return _retry(context, "booking_prompt")

    return FlowTransition(context, action="closed")


def buttons_for_stage(
    context: FlowContext,
    *,
    qualification_options: tuple[str, ...],
    exam_menu: ExamMenuFile,
    slots: tuple[tuple[int, str], ...] = (),
) -> list[QuickReply]:
    """Build only the action buttons accepted by the current stage."""
    buttons: list[tuple[str, str]]
    if context.stage is FlowStage.consent:
        buttons = [("I agree", "consent:agree")]
    elif context.stage is FlowStage.qualification:
        buttons = [
            (label, f"qualification:{index}")
            for index, label in enumerate(qualification_options)
        ]
    elif context.stage is FlowStage.exam_category:
        start = max(0, context.category_page) * 3
        categories = exam_menu.categories[start : start + 3]
        buttons = [
            (item.display_name, f"category:{item.category_id}") for item in categories
        ]
        if start + 3 < len(exam_menu.categories):
            buttons.append(("More", "category:more"))
        elif context.category_page > 0:
            buttons.append(("Back", "category:back"))
    elif context.stage is FlowStage.exam:
        buttons = [
            (item.display_name, f"exam:{item.exam_id}")
            for item in exam_menu.exams
            if item.category == context.exam_category and item.status == "ACTIVE"
        ][:3]
        buttons.append(("Back", "exam:back"))
    elif context.stage is FlowStage.eligibility:
        buttons = [
            ("Check my eligibility", "eligibility:check"),
            ("Course options", "flow:courses"),
        ]
    elif context.stage is FlowStage.course_options:
        counsellor_label = (
            "Resume counselling request"
            if context.counselling_resume
            else "Talk to a counsellor"
        )
        buttons = [
            ("View batch timings", "course:batch_timings"),
            ("View course fees", "course:fees"),
            ("Request a demo class", "course:demo_class"),
            ("Book counselling", "booking:create"),
        ]
        if not context.counselling_request_submitted:
            buttons.append((counsellor_label, "counselling:start"))
    elif context.stage is FlowStage.contact:
        buttons = [
            ("Back to courses", "contact:back"),
            ("Share phone number", "contact:shared"),
            ("Type a phone number", "contact:manual"),
            ("Contact me here", "contact:here"),
            ("Cancel request", "contact:cancel"),
        ]
    elif context.stage is FlowStage.contact_manual:
        buttons = [
            ("Back", "contact:back"),
            ("Contact me here", "contact:here"),
            ("Cancel request", "contact:cancel"),
        ]
    elif context.stage is FlowStage.request_received:
        buttons = [("Main menu", "nav:main")]
    elif context.stage is FlowStage.booking:
        buttons = [(label, f"slot:{index}") for index, label in slots]
        if not buttons:
            buttons = [("Show available times", "booking:create")]
        buttons.append(("Back", "booking:back"))
    else:
        buttons = []
    replies = [
        QuickReply(
            action_id=action,
            label=label,
            send_text=action,
            request_contact=(
                context.stage is FlowStage.contact and action == "contact:shared"
            ),
        )
        for label, action in buttons
    ]
    if context.stage is FlowStage.counselling_review:
        replies = [
            QuickReply(
                action_id="counselling:confirm",
                label="Confirm request",
                send_text="counselling:confirm",
            ),
            QuickReply(
                action_id="counselling:back",
                label="Back",
                send_text="counselling:back",
            ),
            QuickReply(
                action_id="counselling:cancel",
                label="Cancel request",
                send_text="counselling:cancel",
            ),
            QuickReply(action_id="nav:main", label="Main menu", send_text="nav:main"),
        ]
    return replies


def evaluate_eligibility(
    age_years: int | None,
    qualification: str | None,
    verified_summaries: tuple[str, ...],
    qualification_options: tuple[str, ...],
) -> EligibilityStatus:
    """Evaluate only a verified summary with an explicit supported rule shape.

    Supported source summaries state an age range as ``age 18-32`` and name
    the allowed qualification option(s). Incomplete or different wording must
    be confirmed by staff rather than inferred.
    """
    if age_years is None or qualification is None or not verified_summaries:
        return EligibilityStatus.to_confirm
    summaries = " ".join(verified_summaries).casefold()
    age_match = re.search(r"\bage\s*(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\b", summaries)
    if age_match is None:
        return EligibilityStatus.to_confirm
    min_age, max_age = (int(value) for value in age_match.groups())
    named_options = tuple(
        option for option in qualification_options if option.casefold() in summaries
    )
    if not named_options:
        return EligibilityStatus.to_confirm
    if age_years < min_age or age_years > max_age or qualification not in named_options:
        return EligibilityStatus.not_eligible
    return EligibilityStatus.eligible


def _next(
    context: FlowContext,
    stage: FlowStage,
    key: str,
    now: datetime,
    *,
    action: str = "reply",
) -> FlowTransition:
    updated = context.model_copy(update={"stage": stage, "updated_at": now})
    return FlowTransition(updated, action=action, text_key=key)


def _retry(context: FlowContext, key: str) -> FlowTransition:
    return FlowTransition(context, action="retry", text_key=key, retry=True)


def _parse_age(value: str) -> int | None:
    if re.fullmatch(r"\d{1,2}", value.strip()) is None:
        return None
    age = int(value)
    return age if 14 <= age <= 70 else None


def _action_index(value: str, prefix: str) -> int | None:
    match = re.fullmatch(rf"{re.escape(prefix)}:(\d+)", value)
    return int(match.group(1)) if match else None


def _looks_like_action(value: str) -> bool:
    return re.fullmatch(r"[a-z_]+:[a-z0-9_:-]+", value.casefold()) is not None


def _contact_review(
    context: FlowContext, method: str, now: datetime
) -> FlowTransition:
    updated = context.model_copy(update={"contact_method": method, "updated_at": now})
    return _next(
        updated, FlowStage.counselling_review, "counselling_review_prompt", now
    )


def _cancel_counselling(context: FlowContext, now: datetime) -> FlowTransition:
    updated = context.model_copy(
        update={
            "stage": FlowStage.course_options,
            "counselling_resume": False,
            "updated_at": now,
        }
    )
    return FlowTransition(updated, action="reply", text_key="counselling_cancelled")


def _next_counselling_field(
    context: FlowContext,
) -> tuple[FlowStage, str] | None:
    required: tuple[tuple[bool, FlowStage, str], ...] = (
        (bool(context.goal and context.goal.strip()), FlowStage.goal, "goal_prompt"),
        (bool(context.name and context.name.strip()), FlowStage.name, "name_prompt"),
        (context.age_years is not None, FlowStage.age, "age_prompt"),
        (
            context.qualification is not None,
            FlowStage.qualification,
            "qualification_prompt",
        ),
        (
            context.exam_category is not None,
            FlowStage.exam_category,
            "category_menu_intro",
        ),
        (context.exam_id is not None, FlowStage.exam, "exam_menu_intro"),
        (
            context.eligibility_status is not None,
            FlowStage.eligibility,
            "eligibility_prompt",
        ),
    )
    return next(((stage, key) for present, stage, key in required if not present), None)


def _continue_counselling_resume(
    context: FlowContext,
    stage: FlowStage,
    key: str,
    now: datetime,
) -> FlowTransition:
    if not context.counselling_resume:
        return _next(context, stage, key, now)
    missing = _next_counselling_field(context)
    if missing is not None:
        next_stage, next_key = missing
        updated = context.model_copy(
            update={"stage": next_stage, "updated_at": now}
        )
        return FlowTransition(updated, action="reply", text_key=next_key)
    if context.contact_method is None:
        return _next(context, FlowStage.contact, "contact_ask", now)
    return _next(
        context, FlowStage.counselling_review, "counselling_review_prompt", now
    )
