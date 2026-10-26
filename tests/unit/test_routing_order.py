"""High priority routes bypass factual retrieval and LLM answering."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from coaching_inquiry_engine.adapters.calendar_fake import FakeCalendar
from coaching_inquiry_engine.adapters.llm_fake import FakeLlmAdapter
from coaching_inquiry_engine.adapters.messenger_fake import FakeMessenger
from coaching_inquiry_engine.agent.config import CONVERSATION_TEXTS
from coaching_inquiry_engine.agent.conversation import ConversationContext, resolve_text
from coaching_inquiry_engine.domain.config import BOOKING_TZ
from coaching_inquiry_engine.domain.decisions import SlotOption
from coaching_inquiry_engine.domain.models import LeadStatus
from coaching_inquiry_engine.domain.safety import SafetyKeywords
from coaching_inquiry_engine.ports.llm import SanitizedMessage
from coaching_inquiry_engine.worker import Worker

_NOW = datetime(2026, 10, 26, 8, 0, tzinfo=BOOKING_TZ)
_LEAD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _keywords() -> SafetyKeywords:
    return SafetyKeywords.model_validate(
        {
            "review_status": "PENDING_ACADEMIC_HEAD_REVIEW",
            "categories": {
                category: {
                    "en": [f"trigger {category}"],
                    "hi": [f"hindi {category}"],
                    "hinglish": [f"hinglish {category}"],
                }
                for category in (
                    "distress",
                    "self_harm",
                    "minor_signal",
                    "scam_request",
                    "fee_dispute",
                    "complaint",
                    "human_request",
                    "injection_attempt",
                )
            },
        }
    )


async def _turn(text: str, *, answering: bool = True):
    llm = FakeLlmAdapter()
    messenger = FakeMessenger()
    worker = Worker(
        cast(object, None),
        cast(object, None),
        llm,
        messenger,
        _keywords(),
        FakeCalendar(),
        answering_enabled=answering,
    )
    result = await worker.process_turn(
        lead_id=_LEAD_ID,
        recipient="session",
        inbound_text=text,
        context=ConversationContext(),
        prior_messages=[SanitizedMessage(role="user", text=text)],
        consent_granted=True,
        slot_options=[SlotOption(index=0, label="morning")],
        now=_NOW,
    )
    return result, llm, messenger


async def test_counsellor_request_routes_to_handoff_before_knowledge_lookup() -> None:
    result, llm, messenger = await _turn("I would like to talk to a counsellor")

    assert result.text_keys == ["human_handoff"]
    assert result.status is LeadStatus.escalated
    assert messenger.sent_texts == [
        ("session", CONVERSATION_TEXTS["human_handoff"])
    ]
    assert llm.calls == 0


async def test_safety_trigger_routes_before_human_or_knowledge_answering() -> None:
    result, llm, messenger = await _turn(
        "trigger distress; I would like to talk to a counsellor"
    )

    assert result.text_keys == ["distress_support"]
    assert messenger.sent_texts == [
        ("session", CONVERSATION_TEXTS["distress_support"])
    ]
    assert llm.calls == 0


async def test_greeting_still_returns_welcome_key_without_llm() -> None:
    result, llm, messenger = await _turn("hi")

    assert result.text_keys == ["greeting_welcome"]
    assert messenger.sent_texts == [
        ("session", resolve_text("greeting_welcome", display_name="coaching-enquiry"))
    ]
    assert llm.calls == 0
