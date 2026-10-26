"""Consent aggregate persistence. Latest row per channel is authoritative."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from coaching_inquiry_engine.db.models import ConsentRow
from coaching_inquiry_engine.domain.models import ContactChannel


class ConsentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_consent(
        self, lead_id: UUID, channel: ContactChannel, wording_version: str
    ) -> None:
        self._session.add(
            ConsentRow(
                lead_id=lead_id,
                channel=channel.value,
                wording_version=wording_version,
            )
        )
        await self._session.flush()

    async def revoke_consent(self, lead_id: UUID, channel: ContactChannel) -> None:
        latest_id = await self._session.scalar(
            select(ConsentRow.id)
            .where(
                ConsentRow.lead_id == lead_id,
                ConsentRow.channel == channel.value,
            )
            .order_by(ConsentRow.granted_at.desc(), ConsentRow.id.desc())
            .limit(1)
        )
        if latest_id is None:
            return
        await self._session.execute(
            update(ConsentRow)
            .where(ConsentRow.id == latest_id)
            .values(revoked_at=func.now())
        )

    async def latest_consent_granted(
        self, lead_id: UUID, channel: ContactChannel
    ) -> bool:
        row = await self._session.scalar(
            select(ConsentRow)
            .where(
                ConsentRow.lead_id == lead_id,
                ConsentRow.channel == channel.value,
            )
            .order_by(ConsentRow.granted_at.desc(), ConsentRow.id.desc())
            .limit(1)
        )
        if row is None:
            return False
        return row.revoked_at is None

    async def list_for_lead(self, lead_id: UUID) -> list[ConsentRow]:
        return list(
            await self._session.scalars(
                select(ConsentRow)
                .where(ConsentRow.lead_id == lead_id)
                .order_by(ConsentRow.granted_at.desc(), ConsentRow.id.desc())
            )
        )
