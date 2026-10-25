"""Escalations persist one staff alert beside context in the same transaction."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from coaching_inquiry_engine.adapters.calendar_fake import FakeCalendar
from coaching_inquiry_engine.adapters.llm_fake import FakeLlmAdapter
from coaching_inquiry_engine.adapters.messenger_fake import FakeMessenger
from coaching_inquiry_engine.agent.conversation import ConversationContext
from coaching_inquiry_engine.domain.decisions import AgentDecision, NextAction
from coaching_inquiry_engine.domain.models import LeadStatus, QualifyFlags
from coaching_inquiry_engine.domain.safety import SafetyKeywords
from coaching_inquiry_engine.ports.llm import SanitizedMessage
from coaching_inquiry_engine.services.escalation_service import StaffAlertPayload
from coaching_inquiry_engine.worker import Worker

_NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
_LEAD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_CATEGORIES = (
    "distress",
    "self_harm",
    "minor_signal",
    "scam_request",
    "fee_dispute",
    "complaint",
    "human_request",
    "injection_attempt",
)


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
                for name in _CATEGORIES
            },
        }
    )


@pytest.mark.parametrize(
    ("text", "context"),
    [
        ("trigger distress", ConversationContext()),
        ("trigger minor_signal", ConversationContext()),
        ("trigger scam_request", ConversationContext()),
        ("trigger complaint", ConversationContext()),
        ("trigger human_request", ConversationContext()),
        (
            "trigger injection_attempt",
            ConversationContext(
                injection_count=1,
                flags=QualifyFlags(injection_attempt=True),
            ),
        ),
    ],
)
async def test_each_escalation_writes_one_staff_alert_with_context(
    text: str,
    context: ConversationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeLeadRepository:
        def __init__(self, session: object) -> None:
            self.session = session
            self.saved: list[tuple[object, ...]] = []

        async def save_conversation_context(
            self,
            lead_id: UUID,
            context_data: dict[str, object],
            profile: object,
            status: LeadStatus,
        ) -> None:
            self.saved.append(
                (self.session, lead_id, context_data, profile, status)
            )

    class FakeOutboxRepository:
        @staticmethod
        async def enqueue_in_session(
            session: object,
            *,
            lead_id: UUID,
            target: str,
            payload: dict[str, object],
            available_at: datetime,
        ) -> object:
            enqueued.append((session, lead_id, target, payload, available_at))
            return object()

    enqueued: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "coaching_inquiry_engine.worker.OutboxRepository", FakeOutboxRepository
    )
    worker = Worker(
        cast(object, None),
        cast(object, None),
        FakeLlmAdapter(
            [
                AgentDecision(
                    next_action=NextAction.ask_field,
                    reply_text="untrusted model text",
                    prompt_version="upsc_v0.2",
                )
            ]
        ),
        FakeMessenger(),
        _keywords(),
        FakeCalendar(),
        llm_max_attempts=1,
    )
    result = await worker.process_turn(
        lead_id=_LEAD_ID,
        recipient="opaque-session-ref",
        inbound_text=text,
        context=context,
        prior_messages=[SanitizedMessage(role="user", text=text)],
        consent_granted=True,
        slot_options=[],
        now=_NOW,
    )
    assert result.staff_alert_payload is not None
    assert isinstance(result.staff_alert_payload, StaffAlertPayload)

    session = object()
    lead_repository = FakeLeadRepository(session)
    await Worker._persist_context_and_staff_alert(
        session=session,
        leads=cast(object, lead_repository),
        lead_id=_LEAD_ID,
        result=result,
        now=_NOW,
    )

    assert len(lead_repository.saved) == 1
    assert len(enqueued) == 1
    assert lead_repository.saved[0][0] is session
    assert enqueued[0][0] is session
    assert enqueued[0][1:3] == (_LEAD_ID, "staff_alert")
    assert enqueued[0][3] == result.staff_alert_payload.model_dump(mode="json")
    if text == "trigger injection_attempt":
        assert result.staff_alert_payload.reason == "injection_repeat"
