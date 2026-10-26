"""Deterministic conversation state machine. Scripted inputs only; no I/O."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from coaching_inquiry_engine.agent.config import (
    CONVERSATION_TEXTS,
    FOLLOW_UP_AFTER_MINUTES,
    IDLE_CLOSE_MINUTES,
    OFF_TOPIC_LIMIT,
    REPEATED_QUESTION_LIMIT,
)
from coaching_inquiry_engine.domain.models import (
    LeadProfile,
    LeadStatus,
    QualifyFlags,
    Target,
)
from coaching_inquiry_engine.domain.qualify import qualify

# Members are generated from config, so mypy cannot enumerate them statically.
ConversationTextKey = StrEnum(  # type: ignore[misc]
    "ConversationTextKey", {key: key for key in CONVERSATION_TEXTS}
)


class ConversationState(StrEnum):
    NEW = "NEW"
    QUALIFYING = "QUALIFYING"
    ANSWERING_QUESTION = "ANSWERING_QUESTION"
    OFFERING_SLOTS = "OFFERING_SLOTS"
    BOOKED = "BOOKED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class Field(StrEnum):
    stage = "stage"
    target = "target"
    timeline = "timeline"
    contact = "contact"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationContext(_StrictModel):
    state: ConversationState = ConversationState.NEW
    profile: LeadProfile = LeadProfile()
    flags: QualifyFlags = QualifyFlags()
    injection_count: int = 0
    off_topic_count: int = 0
    repeated_question_count: int = 0
    last_asked_field: Field | None = None
    message_count: int = 0
    name: str | None = None
    selected_category: str | None = None
    selected_exam: str | None = None
    category_page: int = 0
    eligibility_step: str | None = None
    age_band: str | None = None
    qualification_band: str | None = None


class InboundMessage(_StrictModel):
    text: str
    extracted_fields: LeadProfile
    detected_flags: QualifyFlags
    is_off_topic: bool = False
    extracted_name: str | None = None


class SlotSelected(_StrictModel):
    offer_id: str


class IdleTimeout(_StrictModel):
    idle_minutes: int


class SendText(_StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text_key: str

    @field_validator("text_key")
    @classmethod
    def require_configured_key(cls, value: str) -> str:
        if value not in CONVERSATION_TEXTS:
            raise ValueError("text_key must be a configured conversation text key")
        return value


def resolve_text(key: str, **placeholders: str) -> str:
    """Return configured message text for a valid key.

    Time values must not be baked into templates. Pass the system-generated
    slot label as ``label`` when the template includes that placeholder.
    """
    if key not in CONVERSATION_TEXTS:
        raise ValueError("key must be a configured conversation text key")
    text = CONVERSATION_TEXTS[key]
    if placeholders:
        return text.format(**placeholders)
    return text


class AskField(_StrictModel):
    field: Field


class OfferSlots(_StrictModel):
    pass


class NotifyStaff(_StrictModel):
    reason: str
    status: LeadStatus


class ScheduleFollowUp(_StrictModel):
    after_minutes: int


class CloseConversation(_StrictModel):
    reason: str


type ConversationEvent = InboundMessage | SlotSelected | IdleTimeout
type ConversationAction = (
    SendText
    | AskField
    | OfferSlots
    | NotifyStaff
    | ScheduleFollowUp
    | CloseConversation
)

_TERMINAL_STATES = frozenset(
    {
        ConversationState.BOOKED,
        ConversationState.ESCALATED,
        ConversationState.CLOSED,
    }
)
_ESCALATION_STATUSES = frozenset(
    {LeadStatus.escalated, LeadStatus.minor_linked}
)


def next_missing_field(profile: LeadProfile) -> Field | None:
    """Return the next qualifying field to collect, in fixed order."""
    if profile.stage is None:
        return Field.stage
    if profile.target is None:
        return Field.target
    if profile.timeline is None:
        return Field.timeline
    if profile.contact is None:
        return Field.contact
    return None


def handle_event(
    ctx: ConversationContext,
    event: ConversationEvent,
    offered_targets: frozenset[Target],
    now: datetime,
) -> tuple[ConversationContext, list[ConversationAction]]:
    """Advance conversation state.

    `now` is supplied by the caller; never read the clock.
    """
    _ = now
    if ctx.state in _TERMINAL_STATES:
        return ctx, []
    if isinstance(event, IdleTimeout):
        return _handle_idle(ctx, event)
    if isinstance(event, SlotSelected):
        return _handle_slot_selected(ctx)
    return _handle_inbound(ctx, event, offered_targets)


def _handle_idle(
    ctx: ConversationContext, event: IdleTimeout
) -> tuple[ConversationContext, list[ConversationAction]]:
    if event.idle_minutes < IDLE_CLOSE_MINUTES:
        return ctx, []
    closed = ctx.model_copy(update={"state": ConversationState.CLOSED})
    return closed, [ScheduleFollowUp(after_minutes=FOLLOW_UP_AFTER_MINUTES)]


def _handle_slot_selected(
    ctx: ConversationContext,
) -> tuple[ConversationContext, list[ConversationAction]]:
    if ctx.state is not ConversationState.OFFERING_SLOTS:
        return ctx, []
    booked = ctx.model_copy(update={"state": ConversationState.BOOKED})
    return booked, [SendText(text_key="booking_confirmed")]


def _handle_inbound(
    ctx: ConversationContext,
    event: InboundMessage,
    offered_targets: frozenset[Target],
) -> tuple[ConversationContext, list[ConversationAction]]:
    profile = _merge_profile(ctx.profile, event.extracted_fields)
    flags = _merge_flags(ctx.flags, event.detected_flags)
    injection_count = ctx.injection_count + int(event.detected_flags.injection_attempt)
    ctx = ctx.model_copy(
        update={
            "profile": profile,
            "flags": flags,
            "injection_count": injection_count,
            "message_count": ctx.message_count + 1,
            "name": event.extracted_name or ctx.name,
        }
    )
    status = qualify(profile, flags, offered_targets)
    if status in _ESCALATION_STATUSES:
        return _escalate(ctx, reason=status.value, status=status)

    if event.detected_flags.injection_attempt and ctx.injection_count >= 2:
        return _escalate(ctx, reason="injection_repeat", status=status)

    first_injection = (
        event.detected_flags.injection_attempt and ctx.injection_count == 1
    )

    if event.is_off_topic:
        updated, actions = _handle_off_topic(ctx, status)
        return _prepend_injection_decline(updated, actions, first_injection)

    if ctx.state is ConversationState.OFFERING_SLOTS:
        return _prepend_injection_decline(ctx, [], first_injection)

    if status is LeadStatus.qualified and next_missing_field(profile) is None:
        offered = ctx.model_copy(
            update={
                "state": ConversationState.OFFERING_SLOTS,
                "last_asked_field": None,
                "repeated_question_count": 0,
            }
        )
        return _prepend_injection_decline(offered, [OfferSlots()], first_injection)

    missing = next_missing_field(profile)
    if missing is None:
        updated = ctx.model_copy(update={"state": ConversationState.QUALIFYING})
        if status is LeadStatus.nurture:
            return _prepend_injection_decline(
                updated, [SendText(text_key="nurture")], first_injection
            )
        if status is LeadStatus.out_of_scope:
            return _prepend_injection_decline(
                updated, [SendText(text_key="out_of_scope")], first_injection
            )
        raise AssertionError(
            f"Unexpected lead status without a missing field: {status}"
        )
    updated, actions = _ask_missing_field(ctx, missing, offered_targets)
    return _prepend_injection_decline(updated, actions, first_injection)


def _prepend_injection_decline(
    ctx: ConversationContext,
    actions: list[ConversationAction],
    should_decline: bool,
) -> tuple[ConversationContext, list[ConversationAction]]:
    if should_decline:
        return ctx, [SendText(text_key="injection_decline"), *actions]
    return ctx, actions


def _handle_off_topic(
    ctx: ConversationContext, status: LeadStatus
) -> tuple[ConversationContext, list[ConversationAction]]:
    count = ctx.off_topic_count + 1
    updated = ctx.model_copy(update={"off_topic_count": count})
    actions: list[ConversationAction] = [SendText(text_key="off_topic_redirect")]
    if count >= OFF_TOPIC_LIMIT:
        return _escalate(
            updated, reason="off_topic_limit", status=status, extra=actions
        )
    return updated, actions


def _ask_missing_field(
    ctx: ConversationContext,
    missing: Field,
    offered_targets: frozenset[Target],
) -> tuple[ConversationContext, list[ConversationAction]]:
    if missing is ctx.last_asked_field:
        repeats = ctx.repeated_question_count + 1
        if repeats >= REPEATED_QUESTION_LIMIT:
            return _escalate(
                ctx.model_copy(update={"repeated_question_count": repeats}),
                reason="unresolved",
                status=qualify(ctx.profile, ctx.flags, offered_targets),
            )
        asked = ctx.model_copy(
            update={
                "state": ConversationState.QUALIFYING,
                "repeated_question_count": repeats,
                "last_asked_field": missing,
            }
        )
        return asked, [AskField(field=missing)]

    asked = ctx.model_copy(
        update={
            "state": ConversationState.QUALIFYING,
            "repeated_question_count": 0,
            "last_asked_field": missing,
        }
    )
    return asked, [AskField(field=missing)]


def _escalate(
    ctx: ConversationContext,
    *,
    reason: str,
    status: LeadStatus,
    extra: list[ConversationAction] | None = None,
) -> tuple[ConversationContext, list[ConversationAction]]:
    escalated = ctx.model_copy(update={"state": ConversationState.ESCALATED})
    actions = list(extra or [])
    actions.append(NotifyStaff(reason=reason, status=status))
    return escalated, actions


def _merge_profile(base: LeadProfile, extracted: LeadProfile) -> LeadProfile:
    return LeadProfile(
        stage=base.stage if extracted.stage is None else extracted.stage,
        target=base.target if extracted.target is None else extracted.target,
        timeline=base.timeline if extracted.timeline is None else extracted.timeline,
        contact=base.contact if extracted.contact is None else extracted.contact,
    )


def _merge_flags(base: QualifyFlags, detected: QualifyFlags) -> QualifyFlags:
    return QualifyFlags(
        is_minor=base.is_minor or detected.is_minor,
        distress_detected=base.distress_detected or detected.distress_detected,
        fee_dispute=base.fee_dispute or detected.fee_dispute,
        complaint=base.complaint or detected.complaint,
        scam_signal=base.scam_signal or detected.scam_signal,
        self_harm=base.self_harm or detected.self_harm,
        human_request=base.human_request or detected.human_request,
        injection_attempt=base.injection_attempt or detected.injection_attempt,
    )
