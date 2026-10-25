"""Postgres 16 constraints and Alembic 0002 upgrade/downgrade."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from coaching_inquiry_engine.db.base import Base
from coaching_inquiry_engine.db.encryption import ContactCipher
from coaching_inquiry_engine.db.models import BookingRow, SlotOfferRow
from coaching_inquiry_engine.db.repositories import LeadRepository
from coaching_inquiry_engine.domain.models import BookingStatus, ContactChannel

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 10, 26, tzinfo=UTC)
_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    cfg = Config(str(_ROOT / "alembic.ini"))
    return cfg


async def test_unique_idempotency_key_on_bookings(
    session: AsyncSession, cipher: ContactCipher
) -> None:
    leads = LeadRepository(session, cipher)
    lead = await leads.get_or_create_lead(ContactChannel.whatsapp, "book-key")
    first = SlotOfferRow(
        lead_id=lead.id,
        option_index=0,
        start=_NOW,
        duration_min=30,
        expires_at=_NOW + timedelta(minutes=30),
        used=True,
    )
    second = SlotOfferRow(
        lead_id=lead.id,
        option_index=1,
        start=_NOW + timedelta(minutes=30),
        duration_min=30,
        expires_at=_NOW + timedelta(minutes=30),
        used=True,
    )
    session.add_all([first, second])
    await session.flush()
    session.add(
        BookingRow(
            lead_id=lead.id,
            offer_id=first.id,
            idempotency_key=f"{lead.id}:{first.id}",
            start=_NOW,
            status=BookingStatus.confirmed.value,
            calendar_event_id="evt-1",
        )
    )
    await session.flush()
    session.add(
        BookingRow(
            lead_id=lead.id,
            offer_id=second.id,
            idempotency_key=f"{lead.id}:{first.id}",
            start=_NOW,
            status=BookingStatus.confirmed.value,
            calendar_event_id="evt-2",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_active_offer_lead_option_index_is_unique(
    session: AsyncSession, cipher: ContactCipher
) -> None:
    leads = LeadRepository(session, cipher)
    lead = await leads.get_or_create_lead(ContactChannel.whatsapp, "offer-idx")
    session.add(
        SlotOfferRow(
            lead_id=lead.id,
            option_index=0,
            start=_NOW,
            duration_min=30,
            expires_at=_NOW + timedelta(minutes=30),
            used=False,
        )
    )
    await session.flush()
    session.add(
        SlotOfferRow(
            lead_id=lead.id,
            option_index=0,
            start=_NOW + timedelta(minutes=30),
            duration_min=30,
            expires_at=_NOW + timedelta(minutes=30),
            used=False,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_migration_0002_upgrades_and_downgrades(
    engine: AsyncEngine,
) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))

    cfg = _alembic_config()
    await asyncio.to_thread(command.upgrade, cfg, "head")
    await asyncio.to_thread(command.downgrade, cfg, "-1")
    await asyncio.to_thread(command.upgrade, cfg, "head")

    async with engine.connect() as connection:
        column = await connection.scalar(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'slot_offers'
                  AND column_name = 'option_index'
                """
            )
        )
        index = await connection.scalar(
            text(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'slot_offers'
                  AND indexname = 'uq_slot_offers_active_lead_option'
                """
            )
        )
    assert column == "option_index"
    assert index == "uq_slot_offers_active_lead_option"


async def test_used_offer_does_not_block_same_index(
    session: AsyncSession, cipher: ContactCipher
) -> None:
    leads = LeadRepository(session, cipher)
    lead = await leads.get_or_create_lead(ContactChannel.whatsapp, "offer-used-idx")
    session.add(
        SlotOfferRow(
            lead_id=lead.id,
            option_index=0,
            start=_NOW,
            duration_min=30,
            expires_at=_NOW + timedelta(minutes=30),
            used=True,
        )
    )
    session.add(
        SlotOfferRow(
            lead_id=lead.id,
            option_index=0,
            start=_NOW + timedelta(minutes=30),
            duration_min=30,
            expires_at=_NOW + timedelta(minutes=30),
            used=False,
        )
    )
    await session.flush()
