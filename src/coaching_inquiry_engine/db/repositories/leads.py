"""Lead aggregate persistence. Identity, contact protection, and retention."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from coaching_inquiry_engine.db.encryption import ContactCipher
from coaching_inquiry_engine.db.mapping import lead_from_row
from coaching_inquiry_engine.db.models import LeadRow
from coaching_inquiry_engine.domain.models import (
    Contact,
    ContactChannel,
    Lead,
    LeadStatus,
)


class LeadRepository:
    def __init__(self, session: AsyncSession, cipher: ContactCipher) -> None:
        self._session = session
        self._cipher = cipher

    async def get_or_create_lead(
        self, channel: ContactChannel, external_user_id: str
    ) -> Lead:
        stmt = (
            insert(LeadRow)
            .values(
                channel=channel.value,
                external_user_id=external_user_id,
                status=LeadStatus.nurture.value,
            )
            .on_conflict_do_nothing(constraint="uq_leads_channel_external_user_id")
        )
        await self._session.execute(stmt)
        row = await self._session.scalar(
            select(LeadRow).where(
                LeadRow.channel == channel.value,
                LeadRow.external_user_id == external_user_id,
            )
        )
        if row is None:
            raise RuntimeError("lead row missing after get_or_create")
        return lead_from_row(row)

    async def set_contact(self, lead_id: UUID, contact: Contact) -> Lead:
        row = await self._session.get(LeadRow, lead_id)
        if row is None:
            raise KeyError(f"lead {lead_id} not found")
        row.name = contact.name
        row.contact_encrypted = self._cipher.encrypt(contact.value)
        row.contact_hash = self._cipher.hash_contact(contact.value)
        await self._session.flush()
        await self._session.refresh(row, attribute_names=["updated_at"])
        return lead_from_row(row)

    async def delete_expired_leads(self, now: datetime, retention_days: int) -> int:
        cutoff = now - timedelta(days=retention_days)
        result = await self._session.execute(
            delete(LeadRow).where(
                LeadRow.status == LeadStatus.lost.value,
                LeadRow.updated_at < cutoff,
            )
        )
        return result.rowcount or 0
