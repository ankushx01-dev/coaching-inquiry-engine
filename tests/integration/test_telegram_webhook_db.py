"""Telegram update idempotency and consent persistence against PostgreSQL."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from coaching_inquiry_engine.adapters.clock import SystemClock
from coaching_inquiry_engine.agent.config import CONVERSATION_TEXTS
from coaching_inquiry_engine.config import Settings
from coaching_inquiry_engine.db.models import LeadRow
from coaching_inquiry_engine.db.repositories.consents import ConsentRepository
from coaching_inquiry_engine.db.repositories.leads import LeadRepository
from coaching_inquiry_engine.db.repositories.messages import MessageRepository
from coaching_inquiry_engine.domain.flow import (
    EligibilityStatus,
    FlowContext,
    FlowStage,
)
from coaching_inquiry_engine.domain.models import (
    ContactChannel,
    LeadProfile,
    LeadStatus,
)
from coaching_inquiry_engine.services.telegram_webhook import TelegramWebhookService

pytestmark = pytest.mark.integration


class _Messenger:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, recipient: str, text: str, quick_replies=()) -> None:
        _ = quick_replies
        self.sent.append((recipient, text))

    async def send_consent_notice(self, recipient: str, text: str) -> None:
        self.sent.append((recipient, text))

    async def answer_callback(self, callback_query_id: str) -> None:
        _ = callback_query_id


async def test_update_id_dedupes_and_consent_requires_agree(engine, cipher) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    messenger = _Messenger()
    settings = Settings(_env_file=None)
    service = TelegramWebhookService(
        session_factory,
        cipher,
        messenger,
        settings,
        SystemClock(),
    )
    start = {
        "update_id": 801,
        "message": {"text": "/start", "chat": {"id": 456}},
    }
    assert await service.process_update(start) is True
    assert await service.process_update(start) is False
    assert len(messenger.sent) == 1
    assert "private AI admissions assistant" in messenger.sent[0][1]
    assert (
        await service.process_update(
            {"update_id": 804, "message": {"text": "/start", "chat": {"id": 456}}}
        )
        is True
    )
    assert len(messenger.sent) == 1

    async with session_factory() as session:
        lead = await LeadRepository(session, cipher).get_by_channel_external_user(
            ContactChannel.telegram, "456"
        )
        assert lead is not None
        assert (
            await ConsentRepository(session).latest_consent_granted(
                lead.id, ContactChannel.telegram
            )
            is False
        )

    agree = {
        "update_id": 802,
        "callback_query": {
            "id": "cb-1",
            "data": "consent:agree",
            "message": {"chat": {"id": 456}},
        },
    }
    await service.process_update(agree)
    async with session_factory() as session:
        lead = await LeadRepository(session, cipher).get_by_channel_external_user(
            ContactChannel.telegram, "456"
        )
        assert lead is not None
        assert (
            await ConsentRepository(session).latest_consent_granted(
                lead.id, ContactChannel.telegram
            )
            is True
        )
    await service.process_update(
        {"update_id": 805, "message": {"text": "/start", "chat": {"id": 456}}}
    )
    assert (
        sum("private AI admissions assistant" in text for _, text in messenger.sent)
        == 1
    )

    stop = {
        "update_id": 803,
        "message": {"text": "/stop", "chat": {"id": 456}},
    }
    await service.process_update(stop)
    async with session_factory() as session:
        lead = await LeadRepository(session, cipher).get_by_channel_external_user(
            ContactChannel.telegram, "456"
        )
        assert lead is not None
        assert (
            await ConsentRepository(session).latest_consent_granted(
                lead.id, ContactChannel.telegram
            )
            is False
        )
    assert messenger.sent[-1][1] == CONVERSATION_TEXTS["consent_stopped"]


async def test_staged_fields_round_trip_on_lead(engine, cipher) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            lead = await LeadRepository(session, cipher).get_or_create_lead(
                ContactChannel.telegram, "round-trip-chat"
            )
            context = {
                "flow": FlowContext(
                    stage=FlowStage.course_options,
                    name="Ankush Rana",
                    age_years=22,
                    eligibility_status=EligibilityStatus.to_confirm,
                ).model_dump(mode="json")
            }
            await LeadRepository(session, cipher).save_conversation_context(
                lead.id, context, LeadProfile(), LeadStatus.nurture
            )
    async with factory() as session:
        lead = await LeadRepository(session, cipher).get_by_id(lead.id)
        assert lead is not None
        assert lead.name == "Ankush Rana"
        assert lead.age_years == 22
        assert lead.eligibility_status == "to_confirm"


async def test_manual_contact_is_encrypted_and_message_history_is_redacted(
    engine, cipher
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    messenger = _Messenger()
    service = TelegramWebhookService(
        factory, cipher, messenger, Settings(_env_file=None), SystemClock()
    )
    async with factory() as session:
        async with session.begin():
            lead = await LeadRepository(session, cipher).get_or_create_lead(
                ContactChannel.telegram, "manual-contact-chat"
            )
            await ConsentRepository(session).record_consent(
                lead.id, ContactChannel.telegram, "telegram-v1"
            )
            await LeadRepository(session, cipher).save_conversation_context(
                lead.id,
                {
                    "flow": FlowContext(
                        stage=FlowStage.contact_manual,
                        name="Asha Sharma",
                        goal="Prepare for civil services",
                        age_years=22,
                        qualification="Graduate",
                        exam_category="civil_services",
                        exam_id="upsc_cse",
                        eligibility_status=EligibilityStatus.to_confirm,
                    ).model_dump(mode="json")
                },
                LeadProfile(),
                LeadStatus.nurture,
            )

    raw_phone = "+91 98765 43210"
    await service.process_update(
        {
            "update_id": 901,
            "message": {
                "text": raw_phone,
                "chat": {"id": "manual-contact-chat"},
                "from": {"id": 8101},
            },
        }
    )
    async with factory() as session:
        lead = await LeadRepository(session, cipher).get_by_channel_external_user(
            ContactChannel.telegram, "manual-contact-chat"
        )
        assert lead is not None
        encrypted = await session.get(LeadRow, lead.id)
        assert encrypted is not None and encrypted.contact_encrypted is not None
        assert raw_phone.encode() not in encrypted.contact_encrypted
        assert (
            await LeadRepository(session, cipher).get_decrypted_contact_value(lead.id)
            == "+919876543210"
        )
        context = await LeadRepository(
            session, cipher
        ).get_conversation_context(lead.id)
        assert context is not None
        assert context["profile"]["contact"]["value"] == "[ENCRYPTED]"
        inbound = await MessageRepository(session).get_by_provider_message_id(
            "telegram-update-901"
        )
        assert inbound is not None
        assert raw_phone not in inbound.body
        assert "contact:manual_saved" in inbound.body


async def test_shared_contact_requires_telegram_owner_match(engine, cipher) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = TelegramWebhookService(
        factory, cipher, _Messenger(), Settings(_env_file=None), SystemClock()
    )
    async with factory() as session:
        async with session.begin():
            lead = await LeadRepository(session, cipher).get_or_create_lead(
                ContactChannel.telegram, "shared-contact-chat"
            )
            await ConsentRepository(session).record_consent(
                lead.id, ContactChannel.telegram, "telegram-v1"
            )
            await LeadRepository(session, cipher).save_conversation_context(
                lead.id,
                {
                    "flow": FlowContext(
                        stage=FlowStage.contact,
                        name="Asha Sharma",
                    ).model_dump(mode="json")
                },
                LeadProfile(),
                LeadStatus.nurture,
            )

    await service.process_update(
        {
            "update_id": 902,
            "message": {
                "contact": {
                    "phone_number": "9876543210",
                    "user_id": 111,
                    "first_name": "Asha",
                },
                "chat": {"id": "shared-contact-chat"},
                "from": {"id": 222},
            },
        }
    )
    async with factory() as session:
        lead = await LeadRepository(session, cipher).get_by_channel_external_user(
            ContactChannel.telegram, "shared-contact-chat"
        )
        assert lead is not None
        assert await LeadRepository(session, cipher).get_decrypted_contact_value(
            lead.id
        ) is None
        inbound = await MessageRepository(session).get_by_provider_message_id(
            "telegram-update-902"
        )
        assert inbound is not None and inbound.body == "contact:invalid"


async def test_shared_contact_is_encrypted_after_sender_validation(
    engine, cipher
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = TelegramWebhookService(
        factory, cipher, _Messenger(), Settings(_env_file=None), SystemClock()
    )
    async with factory() as session:
        async with session.begin():
            lead = await LeadRepository(session, cipher).get_or_create_lead(
                ContactChannel.telegram, "shared-contact-owned-chat"
            )
            await ConsentRepository(session).record_consent(
                lead.id, ContactChannel.telegram, "telegram-v1"
            )
            await LeadRepository(session, cipher).save_conversation_context(
                lead.id,
                {
                    "flow": FlowContext(
                        stage=FlowStage.contact,
                        name="Asha Sharma",
                    ).model_dump(mode="json")
                },
                LeadProfile(),
                LeadStatus.nurture,
            )

    await service.process_update(
        {
            "update_id": 903,
            "message": {
                "contact": {
                    "phone_number": "9876543210",
                    "user_id": 222,
                    "first_name": "Asha",
                },
                "chat": {"id": "shared-contact-owned-chat"},
                "from": {"id": 222},
            },
        }
    )
    async with factory() as session:
        lead = await LeadRepository(session, cipher).get_by_channel_external_user(
            ContactChannel.telegram, "shared-contact-owned-chat"
        )
        assert lead is not None
        stored = await session.get(LeadRow, lead.id)
        assert stored is not None and stored.contact_encrypted is not None
        assert (
            await LeadRepository(session, cipher).get_decrypted_contact_value(lead.id)
            == "+919876543210"
        )
        inbound = await MessageRepository(session).get_by_provider_message_id(
            "telegram-update-903"
        )
        assert inbound is not None and inbound.body == "contact:shared"


async def test_migration_0005_adds_and_drops_only_missing_flow_fields(engine) -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0005_staged_telegram_flow.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0005", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = f"step09i_{uuid4().hex}"
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            await connection.execute(
                text(
                    "CREATE TABLE leads (id UUID PRIMARY KEY, name VARCHAR(60), "
                    "stage VARCHAR(64))"
                )
            )

            def run_upgrade(sync_connection: object) -> None:
                with Operations.context(MigrationContext.configure(sync_connection)):
                    migration.upgrade()

            await connection.run_sync(run_upgrade)
            columns = await connection.run_sync(
                lambda sync_connection: {
                    column["name"]
                    for column in inspect(sync_connection).get_columns("leads")
                }
            )
            assert {
                "name",
                "stage",
                "goal",
                "age_years",
                "eligibility_status",
            } <= columns

            def run_downgrade(sync_connection: object) -> None:
                with Operations.context(MigrationContext.configure(sync_connection)):
                    migration.downgrade()

            await connection.run_sync(run_downgrade)
            columns = await connection.run_sync(
                lambda sync_connection: {
                    column["name"]
                    for column in inspect(sync_connection).get_columns("leads")
                }
            )
            assert columns == {"id", "name", "stage"}
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
