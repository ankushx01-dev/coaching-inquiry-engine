"""End-to-end counselling request creation through the existing job worker."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from coaching_inquiry_engine.adapters.calendar_fake import FakeCalendar
from coaching_inquiry_engine.adapters.clock import SystemClock
from coaching_inquiry_engine.adapters.llm_fake import FakeLlmAdapter
from coaching_inquiry_engine.adapters.messenger_fake import FakeMessenger
from coaching_inquiry_engine.agent.conversation import ConversationContext
from coaching_inquiry_engine.config import Settings
from coaching_inquiry_engine.db.encryption import ContactCipher
from coaching_inquiry_engine.db.models import CounsellingRequestRow, OutboxRow
from coaching_inquiry_engine.db.repositories.consents import ConsentRepository
from coaching_inquiry_engine.db.repositories.jobs import JobRepository
from coaching_inquiry_engine.db.repositories.leads import LeadRepository
from coaching_inquiry_engine.db.repositories.messages import MessageRepository
from coaching_inquiry_engine.domain.exam_menu import load_exam_menu
from coaching_inquiry_engine.domain.flow import (
    EligibilityStatus,
    FlowContext,
    FlowStage,
)
from coaching_inquiry_engine.domain.knowledge import load_knowledge
from coaching_inquiry_engine.domain.models import (
    ContactChannel,
    LeadProfile,
    LeadStatus,
    MessageDirection,
)
from coaching_inquiry_engine.domain.sources import load_sources
from coaching_inquiry_engine.services.safety_keywords import load_safety_keywords
from coaching_inquiry_engine.services.telegram_webhook import TelegramWebhookService
from coaching_inquiry_engine.worker import Worker

pytestmark = pytest.mark.integration


class _Messenger(FakeMessenger):
    def __init__(self) -> None:
        super().__init__()
        self.answered_callbacks: list[str] = []

    async def answer_callback(self, callback_query_id: str) -> None:
        self.answered_callbacks.append(callback_query_id)

    async def send_consent_notice(self, recipient: str, text: str) -> None:
        self.sent_texts.append((recipient, text))


def _worker(
    sessions: async_sessionmaker, cipher: ContactCipher, messenger: _Messenger
) -> Worker:
    institute = load_knowledge("data/institute.yaml")
    topics = yaml.safe_load(
        Path("data/topic_keywords.yaml").read_text(encoding="utf-8")
    )
    return Worker(
        cast(object, sessions),
        cipher,
        FakeLlmAdapter(),
        messenger,
        load_safety_keywords(),
        FakeCalendar(),
        clock=SystemClock(),
        knowledge=institute.entries,
        topic_keywords=topics,
        source_registry=load_sources("data/approved_sources.yaml"),
        exam_menu=load_exam_menu("data/exams.yaml"),
        courses=institute.courses,
        qualification_options=("Class 10", "Class 12", "Graduate"),
    )


async def test_confirm_creates_one_request_and_one_alert_atomically(
    engine: AsyncEngine, cipher: ContactCipher
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    messenger = _Messenger()
    async with sessions() as session:
        async with session.begin():
            lead = await LeadRepository(session, cipher).get_or_create_lead(
                ContactChannel.telegram, "counselling-worker-chat"
            )
            await ConsentRepository(session).record_consent(
                lead.id, ContactChannel.telegram, "telegram-v1"
            )
            context = ConversationContext(
                flow=FlowContext(
                    stage=FlowStage.counselling_review,
                    goal="Prepare for civil services",
                    name="Asha Sharma",
                    age_years=22,
                    qualification="Graduate",
                    exam_category="civil_services",
                    exam_id="upsc_cse",
                    eligibility_status=EligibilityStatus.to_confirm,
                    contact_method="telegram",
                )
            )
            await LeadRepository(session, cipher).save_conversation_context(
                lead.id,
                context.model_dump(mode="json"),
                LeadProfile(),
                LeadStatus.nurture,
            )
            inserted = await MessageRepository(session).insert_message_if_new(
                "worker-request-confirm",
                lead.id,
                MessageDirection.inbound,
                "counselling:confirm",
                SystemClock().now(),
            )
            assert inserted
            message = await MessageRepository(session).get_by_provider_message_id(
                "worker-request-confirm"
            )
            assert message is not None
            await JobRepository(session).enqueue(lead.id, message.id)

    worker = _worker(sessions, cipher, messenger)
    assert await worker.run_once() is True
    assert any(
        text == "Thanks, Asha. Your counselling request has been received."
        for _, text in messenger.sent_texts
    )

    async with sessions() as session:
        request_count = await session.scalar(
            select(func.count()).select_from(CounsellingRequestRow)
        )
        alerts = list(
            await session.scalars(
                select(OutboxRow).where(OutboxRow.target == "staff_alert")
            )
        )
        context = await LeadRepository(session, cipher).get_conversation_context(
            lead.id
        )
        assert request_count == 1
        assert len(alerts) == 1
        assert set(alerts[0].payload) == {
            "lead_id",
            "first_name",
            "exam",
            "eligibility_status",
        }
        assert "Asha Sharma" not in str(alerts[0].payload)
        assert context is not None
        assert context["flow"]["stage"] == "request_received"

    webhook = TelegramWebhookService(
        sessions,
        cipher,
        messenger,
        Settings(_env_file=None),
        SystemClock(),
        load_exam_menu("data/exams.yaml"),
        ("Class 10", "Class 12", "Graduate"),
    )
    await webhook.process_update(
        {
            "update_id": 9991,
            "callback_query": {
                "id": "duplicate-counselling-confirm",
                "data": "counselling:confirm",
                "message": {"chat": {"id": "counselling-worker-chat"}},
            },
        }
    )
    assert messenger.answered_callbacks == ["duplicate-counselling-confirm"]
    async with sessions() as session:
        assert await session.scalar(
            select(func.count()).select_from(CounsellingRequestRow)
        ) == 1
        assert await session.scalar(
            select(func.count())
            .select_from(OutboxRow)
            .where(OutboxRow.target == "staff_alert")
        ) == 1


async def test_confirm_without_consent_creates_no_request_or_staff_alert(
    engine: AsyncEngine, cipher: ContactCipher
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    messenger = _Messenger()
    async with sessions() as session:
        async with session.begin():
            lead = await LeadRepository(session, cipher).get_or_create_lead(
                ContactChannel.telegram, "counselling-no-consent-chat"
            )
            context = ConversationContext(
                flow=FlowContext(
                    stage=FlowStage.counselling_review,
                    goal="Prepare for civil services",
                    name="Asha Sharma",
                    age_years=22,
                    qualification="Graduate",
                    exam_category="civil_services",
                    exam_id="upsc_cse",
                    eligibility_status=EligibilityStatus.to_confirm,
                    contact_method="telegram",
                )
            )
            await LeadRepository(session, cipher).save_conversation_context(
                lead.id,
                context.model_dump(mode="json"),
                LeadProfile(),
                LeadStatus.nurture,
            )
            inserted = await MessageRepository(session).insert_message_if_new(
                "worker-request-no-consent",
                lead.id,
                MessageDirection.inbound,
                "counselling:confirm",
                SystemClock().now(),
            )
            assert inserted
            message = await MessageRepository(session).get_by_provider_message_id(
                "worker-request-no-consent"
            )
            assert message is not None
            await JobRepository(session).enqueue(lead.id, message.id)

    assert await _worker(sessions, cipher, messenger).run_once() is True
    async with sessions() as session:
        assert await session.scalar(
            select(func.count())
            .select_from(CounsellingRequestRow)
            .where(CounsellingRequestRow.lead_id == lead.id)
        ) == 0
        assert await session.scalar(
            select(func.count())
            .select_from(OutboxRow)
            .where(
                OutboxRow.lead_id == lead.id,
                OutboxRow.target == "staff_alert",
            )
        ) == 0
    assert not any(
        "request has been received" in text for _, text in messenger.sent_texts
    )
