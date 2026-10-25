"""Slot-offer and booking persistence. Transaction boundary for a confirmed book."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from coaching_inquiry_engine.db.models import BookingRow, OutboxRow, SlotOfferRow
from coaching_inquiry_engine.domain.models import BookingStatus, OutboxStatus
from coaching_inquiry_engine.domain.slots import SlotOffer
from coaching_inquiry_engine.services.booking_service import (
    OfferDraft,
    crm_outbox_payload,
)


def _offer_from_row(row: SlotOfferRow) -> SlotOffer:
    return SlotOffer(
        id=row.id,
        lead_id=row.lead_id,
        option_index=row.option_index,
        start=row.start,
        duration_min=row.duration_min,
        expires_at=row.expires_at,
        used=row.used,
    )


class BookingRepository:
    def __init__(
        self, session: AsyncSession, *, commit_on_persist: bool = True
    ) -> None:
        self._session = session
        self._commit_on_persist = commit_on_persist

    async def replace_active_offers(
        self, lead_id: UUID, drafts: list[OfferDraft]
    ) -> list[SlotOffer]:
        await self._session.execute(
            delete(SlotOfferRow).where(
                SlotOfferRow.lead_id == lead_id,
                SlotOfferRow.used.is_(False),
            )
        )
        stored: list[SlotOffer] = []
        for draft in drafts:
            row = SlotOfferRow(
                lead_id=lead_id,
                option_index=draft.option_index,
                start=draft.start,
                duration_min=draft.duration_min,
                expires_at=draft.expires_at,
                used=False,
            )
            self._session.add(row)
            await self._session.flush()
            stored.append(_offer_from_row(row))
        return stored

    async def get_offer(self, offer_id: UUID) -> SlotOffer | None:
        row = await self._session.get(SlotOfferRow, offer_id)
        if row is None:
            return None
        return _offer_from_row(row)

    async def get_unused_by_index(
        self, lead_id: UUID, option_index: int
    ) -> SlotOffer | None:
        row = await self._session.scalar(
            select(SlotOfferRow).where(
                SlotOfferRow.lead_id == lead_id,
                SlotOfferRow.option_index == option_index,
                SlotOfferRow.used.is_(False),
            )
        )
        if row is None:
            return None
        return _offer_from_row(row)

    async def list_active_offers(
        self, lead_id: UUID, now: datetime
    ) -> list[SlotOffer]:
        rows = await self._session.scalars(
            select(SlotOfferRow)
            .where(
                SlotOfferRow.lead_id == lead_id,
                SlotOfferRow.used.is_(False),
                SlotOfferRow.expires_at > now,
            )
            .order_by(SlotOfferRow.option_index)
        )
        return [_offer_from_row(row) for row in rows]

    async def persist_booking(
        self,
        *,
        lead_id: UUID,
        offer: SlotOffer,
        idempotency_key: str,
        calendar_event_id: str,
        now: datetime,
    ) -> None:
        async with self._session.begin_nested():
            row = await self._session.get(SlotOfferRow, offer.id)
            if row is None:
                raise KeyError(f"offer {offer.id} not found")
            row.used = True
            self._session.add(
                BookingRow(
                    lead_id=lead_id,
                    offer_id=offer.id,
                    idempotency_key=idempotency_key,
                    start=offer.start,
                    status=BookingStatus.confirmed.value,
                    calendar_event_id=calendar_event_id,
                )
            )
            self._session.add(
                OutboxRow(
                    lead_id=lead_id,
                    target="crm",
                    payload=crm_outbox_payload(
                        lead_id=lead_id,
                        offer_id=offer.id,
                        idempotency_key=idempotency_key,
                        calendar_event_id=calendar_event_id,
                    ),
                    status=OutboxStatus.pending.value,
                    next_attempt_at=now,
                )
            )
            await self._session.flush()
        if self._commit_on_persist:
            await self._session.commit()
