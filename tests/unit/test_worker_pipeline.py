"""Worker pipeline tests use only the fake LLM and messenger adapters."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import httpx
import pytest

from coaching_inquiry_engine.adapters.booking_memory import MemoryBookingStore
from coaching_inquiry_engine.adapters.calendar_fake import FakeCalendar
from coaching_inquiry_engine.adapters.llm_fake import FakeLlmAdapter
from coaching_inquiry_engine.adapters.messenger_fake import FakeMessenger
from coaching_inquiry_engine.agent.config import CONVERSATION_TEXTS
from coaching_inquiry_engine.agent.conversation import ConversationContext
from coaching_inquiry_engine.domain.config import BOOKING_TZ, OFFERED_TARGETS
from coaching_inquiry_engine.domain.decisions import AgentDecision, NextAction
from coaching_inquiry_engine.domain.models import (
    Contact,
    ContactChannel,
    LeadProfile,
    LeadStatus,
    Stage,
    Target,
    Timeline,
)
from coaching_inquiry_engine.domain.safety import SafetyKeywords
from coaching_inquiry_engine.ports.llm import SanitizedMessage
from coaching_inquiry_engine.services.booking_service import BookingService
from coaching_inquiry_engine.worker import Worker

_NOW = datetime(2026, 10, 26, 8, 0, tzinfo=BOOKING_TZ)
_LEAD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _keywords() -> SafetyKeywords:
    return SafetyKeywords.model_validate(
        {
            "review_status": "PENDING_ACADEMIC_HEAD_REVIEW",
            "categories": {
                name: {
                    "en": [f"trigger {name}"],
                    "hi": [f"हिंदी {name}"],
                    "hinglish": [f"hinglish {name}"],
                }
                for name in (
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


def _decision(
    action: NextAction = NextAction.ask_field,
    *,
    reply: str = "MODEL_REPLY_MUST_NOT_BE_SENT",
    updates: dict[str, object] | None = None,
) -> AgentDecision:
    return AgentDecision(
        next_action=action,
        reply_text=reply,
        field_updates=updates or {},
        prompt_version="upsc_v0.2",
    )


def _profile(target: Target = Target.prelims) -> LeadProfile:
    return LeadProfile(
        stage=Stage.first_attempt,
        target=target,
        timeline=Timeline.within_1_month,
        contact=Contact(
            name="Asha Sharma",
            channel=ContactChannel.whatsapp,
            value="9876543210",
        ),
    )


def _worker(
    llm: FakeLlmAdapter,
    messenger: FakeMessenger,
    *,
    offered_targets=frozenset(OFFERED_TARGETS),
) -> Worker:
    return Worker(
        cast(object, None),
        cast(object, None),
        llm,
        messenger,
        _keywords(),
        FakeCalendar(),
        offered_targets=offered_targets,
        llm_max_attempts=1,
    )


async def _turn(
    worker: Worker,
    context: ConversationContext,
    *,
    text: str = "Tell me about the course",
    consent: bool = True,
    booking_service: BookingService | None = None,
):
    return await worker.process_turn(
        lead_id=_LEAD_ID,
        recipient="hashed-session-id",
        inbound_text=text,
        context=context,
        prior_messages=[SanitizedMessage(role="user", text=text)],
        consent_granted=consent,
        slot_options=[],
        now=_NOW,
        booking_service=booking_service,
    )


async def test_qualified_path_sends_only_configured_text_key() -> None:
    llm = FakeLlmAdapter([_decision(NextAction.offer_slots)])
    messenger = FakeMessenger()
    worker = _worker(llm, messenger)
    booking_service = BookingService(FakeCalendar(), MemoryBookingStore())

    result = await _turn(
        worker,
        ConversationContext(profile=_profile()),
        booking_service=booking_service,
    )

    assert result.status is LeadStatus.qualified
    assert result.text_keys == ["offers_refreshed"]
    assert messenger.sent_texts == [
        ("hashed-session-id", CONVERSATION_TEXTS["offers_refreshed"])
    ]
    assert "MODEL_REPLY_MUST_NOT_BE_SENT" not in messenger.sent_texts[0][1]


async def test_out_of_scope_path_sends_configured_key() -> None:
    llm = FakeLlmAdapter([_decision()])
    messenger = FakeMessenger()
    worker = _worker(llm, messenger, offered_targets=frozenset({Target.prelims}))

    result = await _turn(worker, ConversationContext(profile=_profile(Target.mains)))

    assert result.status is LeadStatus.out_of_scope
    assert result.text_keys == ["out_of_scope"]
    assert messenger.sent_texts == [
        ("hashed-session-id", CONVERSATION_TEXTS["out_of_scope"])
    ]


async def test_distress_path_uses_plan_response_key() -> None:
    llm = FakeLlmAdapter([_decision()])
    messenger = FakeMessenger()
    worker = _worker(llm, messenger)

    result = await _turn(
        worker,
        ConversationContext(),
        text="trigger distress",
    )

    assert result.status is LeadStatus.escalated
    assert result.text_keys == ["distress_support"]
    assert messenger.sent_texts == [
        ("hashed-session-id", CONVERSATION_TEXTS["distress_support"])
    ]


async def test_llm_unavailable_sends_fallback_and_preserves_inbound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inbound = SimpleNamespace(
        id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        direction="inbound",
        body="Could you help me?",
    )
    lead = SimpleNamespace(id=_LEAD_ID, external_user_id="hashed-session-id")
    persisted_outbound: list[tuple[object, ...]] = []
    saved_contexts: list[dict[str, object]] = []

    class FakeLeadRepository:
        def __init__(self, _session: object, _cipher: object) -> None:
            pass

        async def get_by_id(self, _lead_id: UUID) -> object:
            return lead

        async def get_conversation_context(
            self, _lead_id: UUID
        ) -> dict[str, object] | None:
            return None

        async def get_decrypted_contact_value(self, _lead_id: UUID) -> None:
            return None

        async def save_conversation_context(
            self,
            _lead_id: UUID,
            context: dict[str, object],
            _profile: LeadProfile,
            _status: LeadStatus,
        ) -> None:
            saved_contexts.append(context)

    class FakeMessageRepository:
        def __init__(self, _session: object) -> None:
            self.inbound = inbound

        async def get_by_id(self, _message_id: UUID) -> object:
            return self.inbound

        async def list_recent(self, _lead_id: UUID, limit: int) -> list[object]:
            assert limit == 10
            return [self.inbound]

        async def insert_message_if_new(self, *args: object) -> bool:
            persisted_outbound.append(args)
            return True

    class FakeBookingRepository:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def list_active_offers(
            self, _lead_id: UUID, _now: datetime
        ) -> list[object]:
            return []

    class FakeConsentRepository:
        def __init__(self, _session: object) -> None:
            pass

        async def latest_consent_granted(
            self, _lead_id: UUID, _channel: ContactChannel
        ) -> bool:
            return True

    class FakeAuditRepository:
        def __init__(self, _session: object) -> None:
            pass

        async def append_audit_event(self, **_kwargs: object) -> None:
            return None

    monkeypatch.setattr(
        "coaching_inquiry_engine.worker.LeadRepository", FakeLeadRepository
    )
    monkeypatch.setattr(
        "coaching_inquiry_engine.worker.MessageRepository", FakeMessageRepository
    )
    monkeypatch.setattr(
        "coaching_inquiry_engine.worker.BookingRepository", FakeBookingRepository
    )
    monkeypatch.setattr(
        "coaching_inquiry_engine.worker.ConsentRepository", FakeConsentRepository
    )
    monkeypatch.setattr(
        "coaching_inquiry_engine.worker.AuditRepository", FakeAuditRepository
    )

    llm = FakeLlmAdapter([httpx.ConnectError("offline")])
    messenger = FakeMessenger()
    worker = _worker(llm, messenger)
    job = SimpleNamespace(
        id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        lead_id=_LEAD_ID,
        inbound_message_id=inbound.id,
    )

    await worker._process_job(cast(object, None), job, _NOW)

    assert inbound.body == "Could you help me?"
    assert persisted_outbound
    assert saved_contexts
    assert messenger.sent_texts == [
        ("hashed-session-id", CONVERSATION_TEXTS["llm_fallback"])
    ]


async def test_outbound_without_consent_is_blocked() -> None:
    llm = FakeLlmAdapter([_decision()])
    messenger = FakeMessenger()
    worker = _worker(llm, messenger)

    result = await _turn(worker, ConversationContext(), consent=False)

    assert result.text_keys == ["ask_stage"]
    assert result.stored_texts == []
    assert messenger.sent_texts == []
