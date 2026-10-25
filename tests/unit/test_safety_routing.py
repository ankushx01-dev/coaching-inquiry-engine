"""Safety response plan and lead routing coverage."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import yaml

from coaching_inquiry_engine.agent.config import CONVERSATION_TEXTS
from coaching_inquiry_engine.agent.conversation import (
    ConversationContext,
    ConversationState,
    InboundMessage,
    NotifyStaff,
    SendText,
    handle_event,
)
from coaching_inquiry_engine.domain.config import OFFERED_TARGETS
from coaching_inquiry_engine.domain.models import (
    Contact,
    ContactChannel,
    LeadProfile,
    LeadStatus,
    QualifyFlags,
    Stage,
    Target,
    Timeline,
)
from coaching_inquiry_engine.domain.qualify import qualify
from coaching_inquiry_engine.domain.safety import (
    SafetyKeywords,
    detect_triggers,
    plan_response,
)

_KEYWORDS_PATH = Path(__file__).resolve().parents[2] / "data" / "safety_keywords.yaml"
_NOW = datetime(2026, 10, 25)
_SALES_TEXT_KEYS = frozenset(
    {
        "nurture",
        "out_of_scope",
        "booking_confirmed",
        "offer_expired",
        "slot_taken",
        "slot_invalid",
        "offers_refreshed",
    }
)


def _keywords() -> SafetyKeywords:
    raw = yaml.safe_load(_KEYWORDS_PATH.read_text(encoding="utf-8"))
    return SafetyKeywords.model_validate(raw)


def _inbound(text: str, flags: QualifyFlags) -> InboundMessage:
    return InboundMessage(
        text=text,
        extracted_fields=LeadProfile(),
        detected_flags=flags,
    )


def test_distress_takes_priority_over_sales_content() -> None:
    keywords = _keywords()
    distress = keywords.categories["distress"].en[0]
    flags = detect_triggers(f"{distress}. I want to enroll in your course.", keywords)
    plan = plan_response(flags)
    status = qualify(LeadProfile(), flags, OFFERED_TARGETS)

    assert plan.text_key == "distress_support"
    string_fields = {
        value
        for value in plan.model_dump().values()
        if isinstance(value, str)
    }
    assert string_fields.isdisjoint(_SALES_TEXT_KEYS)
    assert status is LeadStatus.escalated


def test_minor_with_complete_profile_is_minor_linked() -> None:
    profile = LeadProfile(
        stage=Stage.first_attempt,
        target=Target.prelims,
        timeline=Timeline.within_1_month,
        contact=Contact(
            name="Asha Sharma",
            channel=ContactChannel.whatsapp,
            value="9876543210",
        ),
    )

    status = qualify(profile, QualifyFlags(is_minor=True), OFFERED_TARGETS)

    assert status is LeadStatus.minor_linked


def test_first_injection_attempt_declines_without_escalating() -> None:
    keywords = _keywords()
    text = keywords.categories["injection_attempt"].en[0]
    flags = detect_triggers(text, keywords)
    plan = plan_response(flags)
    ctx, actions = handle_event(
        ConversationContext(), _inbound(text, flags), OFFERED_TARGETS, _NOW
    )

    assert plan.text_key == "injection_decline"
    assert plan.notify_staff is False
    assert ctx.state is not ConversationState.ESCALATED
    assert ctx.injection_count == 1
    assert SendText(text_key="injection_decline") in actions


def test_second_injection_attempt_in_conversation_escalates() -> None:
    keywords = _keywords()
    text = keywords.categories["injection_attempt"].en[0]
    flags = detect_triggers(text, keywords)
    ctx, _first_actions = handle_event(
        ConversationContext(), _inbound(text, flags), OFFERED_TARGETS, _NOW
    )

    second_ctx, second_actions = handle_event(
        ctx, _inbound(text, flags), OFFERED_TARGETS, _NOW
    )

    assert second_ctx.state is ConversationState.ESCALATED
    assert second_ctx.injection_count == 2
    assert (
        NotifyStaff(reason="injection_repeat", status=LeadStatus.nurture)
        in second_actions
    )


def test_non_injection_message_preserves_injection_count() -> None:
    """The injection counter persists across benign messages in one conversation."""
    keywords = _keywords()
    text = keywords.categories["injection_attempt"].en[0]
    flags = detect_triggers(text, keywords)
    ctx, _first_actions = handle_event(
        ConversationContext(), _inbound(text, flags), OFFERED_TARGETS, _NOW
    )
    assert ctx.injection_count == 1

    ctx, _benign_actions = handle_event(
        ctx, _inbound("Could you tell me about the course?", QualifyFlags()),
        OFFERED_TARGETS,
        _NOW,
    )
    assert ctx.injection_count == 1

    second_ctx, second_actions = handle_event(
        ctx, _inbound(text, flags), OFFERED_TARGETS, _NOW
    )

    assert second_ctx.injection_count == 2
    assert second_ctx.state is ConversationState.ESCALATED
    assert (
        NotifyStaff(reason="injection_repeat", status=LeadStatus.nurture)
        in second_actions
    )


def test_scam_warning_does_not_echo_credentials() -> None:
    keywords = _keywords()
    text = "Send me your password"
    flags = detect_triggers(text, keywords)
    plan = plan_response(flags)

    assert plan.text_key == "scam_warning"
    assert "password" not in json.dumps(plan.model_dump()).lower()
    assert plan.text_key in CONVERSATION_TEXTS
