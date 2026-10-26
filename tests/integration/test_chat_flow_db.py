"""Database-backed chat turns exercise intent and verified knowledge flow."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from coaching_inquiry_engine.adapters.calendar_fake import FakeCalendar
from coaching_inquiry_engine.adapters.llm_fake import FakeLlmAdapter
from coaching_inquiry_engine.adapters.messenger_fake import FakeMessenger
from coaching_inquiry_engine.agent.conversation import resolve_text
from coaching_inquiry_engine.db.encryption import ContactCipher
from coaching_inquiry_engine.db.repositories.consents import ConsentRepository
from coaching_inquiry_engine.db.repositories.jobs import JobRepository
from coaching_inquiry_engine.db.repositories.leads import LeadRepository
from coaching_inquiry_engine.db.repositories.messages import MessageRepository
from coaching_inquiry_engine.domain.config import PROMPT_VERSION
from coaching_inquiry_engine.domain.decisions import AgentDecision, NextAction
from coaching_inquiry_engine.domain.knowledge import KnowledgeEntry
from coaching_inquiry_engine.domain.models import ContactChannel, MessageDirection
from coaching_inquiry_engine.services.safety_keywords import load_safety_keywords
from coaching_inquiry_engine.worker import Worker

pytestmark = pytest.mark.integration
_NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


async def _enqueue_turn(
    session: AsyncSession,
    cipher: ContactCipher,
    text_value: str,
    session_key: str,
) -> object:
    lead = await LeadRepository(session, cipher).get_or_create_lead(
        ContactChannel.chat, session_key
    )
    message_repo = MessageRepository(session)
    await message_repo.insert_message_if_new(
        f"chat-flow-{session_key}",
        lead.id,
        MessageDirection.inbound,
        text_value,
        _NOW,
    )
    inbound = await message_repo.get_by_provider_message_id(f"chat-flow-{session_key}")
    assert inbound is not None
    await JobRepository(session).enqueue(lead.id, inbound.id)
    await ConsentRepository(session).record_consent(
        lead.id, ContactChannel.chat, f"consent-{session_key}"
    )
    await session.commit()
    return lead


def _worker(
    engine: object,
    cipher: ContactCipher,
    llm: FakeLlmAdapter,
    messenger: FakeMessenger,
    knowledge: tuple[KnowledgeEntry, ...],
) -> Worker:
    return Worker(
        async_sessionmaker(engine, expire_on_commit=False),
        cipher,
        llm,
        messenger,
        load_safety_keywords(),
        FakeCalendar(),
        llm_max_attempts=1,
        answering_enabled=True,
        knowledge=knowledge,
        topic_keywords={"study_basics": ["study", "strategy"]},
    )


async def test_hi_sends_welcome_without_calling_llm(
    session: AsyncSession,
    engine: object,
    cipher: ContactCipher,
) -> None:
    await _enqueue_turn(session, cipher, "hi", "hello-session")
    llm = FakeLlmAdapter()
    messenger = FakeMessenger()
    worker = _worker(engine, cipher, llm, messenger, ())

    assert await worker.run_once() is True

    assert llm.calls == 0
    assert messenger.sent_texts == [
        (
            "hello-session",
            resolve_text("greeting_welcome", display_name="coaching-enquiry"),
        )
    ]


async def test_verified_knowledge_answer_cites_its_entry_id(
    session: AsyncSession,
    engine: object,
    cipher: ContactCipher,
) -> None:
    await _enqueue_turn(session, cipher, "What is a study strategy?", "facts-session")
    entry = KnowledgeEntry(
        id="study_strategy",
        topic="study_basics",
        text="A study strategy begins with a consistent routine.",
        source_note="Academic review",
        last_verified=date(2026, 10, 20),
        status="VERIFIED",
    )
    llm = FakeLlmAdapter(
        [
            AgentDecision(
                next_action=NextAction.answer_question,
                reply_text="Build a consistent routine [study_strategy].",
                prompt_version=PROMPT_VERSION,
            )
        ]
    )
    messenger = FakeMessenger()
    worker = _worker(engine, cipher, llm, messenger, (entry,))

    assert await worker.run_once() is True

    assert llm.calls == 1
    assert any("[study_strategy]" in text for _recipient, text in messenger.sent_texts)
