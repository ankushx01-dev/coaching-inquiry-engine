"""Integration tests against PostgreSQL 16."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from coaching_inquiry_engine.config import get_settings
from coaching_inquiry_engine.db.encryption import (
    ContactCipher,
    MissingEncryptionKeyError,
)
from coaching_inquiry_engine.db.models import (
    ConsentRow,
    LeadRow,
    MessageRow,
    OutboxRow,
    SlotOfferRow,
)
from coaching_inquiry_engine.db.repositories import (
    ConsentRepository,
    LeadRepository,
    MessageRepository,
)
from coaching_inquiry_engine.domain.models import (
    Contact,
    ContactChannel,
    LeadStatus,
    MessageDirection,
    OutboxStatus,
)
from coaching_inquiry_engine.main import create_app

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 10, 24, tzinfo=UTC)
_PHONE = "9876543210"
_NORMALIZED = "+919876543210"


def _leads(session: AsyncSession, cipher: ContactCipher) -> LeadRepository:
    return LeadRepository(session, cipher)


async def test_duplicate_provider_message_id_is_idempotent(
    session: AsyncSession, cipher: ContactCipher
) -> None:
    leads = _leads(session, cipher)
    messages = MessageRepository(session)
    lead = await leads.get_or_create_lead(ContactChannel.whatsapp, "user-1")

    first = await messages.insert_message_if_new(
        provider_message_id="wa-100",
        lead_id=lead.id,
        direction=MessageDirection.inbound,
        body="hello",
        received_at=_NOW,
    )
    second = await messages.insert_message_if_new(
        provider_message_id="wa-100",
        lead_id=lead.id,
        direction=MessageDirection.inbound,
        body="hello again",
        received_at=_NOW,
    )
    await session.flush()

    count = await session.scalar(select(func.count()).select_from(MessageRow))
    assert first is True
    assert second is False
    assert count == 1


async def test_consent_grant_then_revoke_is_not_granted(
    session: AsyncSession, cipher: ContactCipher
) -> None:
    leads = _leads(session, cipher)
    consents = ConsentRepository(session)
    lead = await leads.get_or_create_lead(ContactChannel.whatsapp, "user-2")

    await consents.record_consent(lead.id, ContactChannel.whatsapp, "wording-v1")
    assert (
        await consents.latest_consent_granted(lead.id, ContactChannel.whatsapp) is True
    )

    await consents.revoke_consent(lead.id, ContactChannel.whatsapp)
    assert (
        await consents.latest_consent_granted(lead.id, ContactChannel.whatsapp) is False
    )


async def test_retention_deletes_only_old_lost_leads_and_children(
    session: AsyncSession, cipher: ContactCipher
) -> None:
    leads = _leads(session, cipher)
    cutoff_days = 365
    old = _NOW - timedelta(days=400)
    recent = _NOW - timedelta(days=1)

    lost_old = await leads.get_or_create_lead(ContactChannel.whatsapp, "lost-old")
    booked = await leads.get_or_create_lead(ContactChannel.whatsapp, "booked-old")
    lost_recent = await leads.get_or_create_lead(ContactChannel.whatsapp, "lost-recent")

    await session.execute(
        update(LeadRow)
        .where(LeadRow.id == lost_old.id)
        .values(status=LeadStatus.lost.value, updated_at=old)
    )
    await session.execute(
        update(LeadRow)
        .where(LeadRow.id == booked.id)
        .values(status=LeadStatus.booked.value, updated_at=old)
    )
    await session.execute(
        update(LeadRow)
        .where(LeadRow.id == lost_recent.id)
        .values(status=LeadStatus.lost.value, updated_at=recent)
    )

    session.add(
        MessageRow(
            lead_id=lost_old.id,
            provider_message_id="retain-1",
            direction=MessageDirection.inbound.value,
            body="hello",
            received_at=_NOW,
        )
    )
    session.add(
        ConsentRow(
            lead_id=lost_old.id,
            channel=ContactChannel.whatsapp.value,
            wording_version="v1",
        )
    )
    session.add(
        SlotOfferRow(
            lead_id=lost_old.id,
            start=_NOW,
            duration_min=30,
            expires_at=_NOW + timedelta(hours=2),
            used=False,
        )
    )
    session.add(
        OutboxRow(
            lead_id=lost_old.id,
            target="whatsapp",
            payload={"text_key": "nurture"},
            status=OutboxStatus.pending.value,
            next_attempt_at=_NOW,
        )
    )
    await session.flush()

    deleted = await leads.delete_expired_leads(_NOW, cutoff_days)
    session.expire_all()

    assert deleted == 1
    assert await session.get(LeadRow, lost_old.id) is None
    assert (
        await session.scalar(
            select(func.count())
            .select_from(MessageRow)
            .where(MessageRow.lead_id == lost_old.id)
        )
        == 0
    )
    assert (
        await session.scalar(
            select(func.count())
            .select_from(ConsentRow)
            .where(ConsentRow.lead_id == lost_old.id)
        )
        == 0
    )
    assert (
        await session.scalar(
            select(func.count())
            .select_from(SlotOfferRow)
            .where(SlotOfferRow.lead_id == lost_old.id)
        )
        == 0
    )
    assert (
        await session.scalar(
            select(func.count())
            .select_from(OutboxRow)
            .where(OutboxRow.lead_id == lost_old.id)
        )
        == 0
    )

    booked_row = await session.get(LeadRow, booked.id)
    recent_row = await session.get(LeadRow, lost_recent.id)
    assert booked_row is not None
    assert booked_row.status == LeadStatus.booked.value
    assert recent_row is not None
    assert recent_row.status == LeadStatus.lost.value


async def test_contact_encrypted_does_not_contain_plaintext(
    session: AsyncSession, cipher: ContactCipher
) -> None:
    leads = _leads(session, cipher)
    lead = await leads.get_or_create_lead(ContactChannel.whatsapp, "user-crypto")
    contact = Contact(
        name="Ada Lovelace",
        channel=ContactChannel.whatsapp,
        value=_PHONE,
    )
    await leads.set_contact(lead.id, contact)
    await session.flush()
    session.expire_all()

    row = await session.get(LeadRow, lead.id)
    assert row is not None
    assert row.contact_encrypted is not None
    assert _PHONE.encode("utf-8") not in row.contact_encrypted
    assert _NORMALIZED.encode("utf-8") not in row.contact_encrypted
    assert contact.value.encode("utf-8") not in row.contact_encrypted
    assert cipher.decrypt(row.contact_encrypted) == _NORMALIZED
    assert row.contact_hash == cipher.hash_contact(_NORMALIZED)


def test_app_raises_at_startup_when_encryption_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIE_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(MissingEncryptionKeyError, match="CIE_ENCRYPTION_KEY"):
            create_app()
    finally:
        get_settings.cache_clear()
