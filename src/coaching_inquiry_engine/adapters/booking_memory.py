"""In-memory BookingStore for unit tests."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from coaching_inquiry_engine.domain.models import BookingStatus, OutboxStatus
from coaching_inquiry_engine.domain.slots import SlotOffer
from coaching_inquiry_engine.services.booking_service import (
    OfferDraft,
    crm_outbox_payload,
)


class OutboxInsertError(RuntimeError):
    """Raised to simulate a failed outbox insert after create_event."""


class MemoryBookingStore:
    def __init__(self) -> None:
        self.offers: dict[UUID, SlotOffer] = {}
        self.bookings: dict[str, dict[str, object]] = {}
        self.outbox: list[dict[str, object]] = []
        self.fail_outbox_once = False

    async def replace_active_offers(
        self, lead_id: UUID, drafts: list[OfferDraft]
    ) -> list[SlotOffer]:
        stale = [
            offer_id
            for offer_id, offer in self.offers.items()
            if offer.lead_id == lead_id and not offer.used
        ]
        for offer_id in stale:
            del self.offers[offer_id]
        stored: list[SlotOffer] = []
        for draft in drafts:
            offer = SlotOffer(
                id=uuid4(),
                lead_id=lead_id,
                option_index=draft.option_index,
                start=draft.start,
                duration_min=draft.duration_min,
                expires_at=draft.expires_at,
                used=False,
            )
            self.offers[offer.id] = offer
            stored.append(offer)
        return stored

    async def get_offer(self, offer_id: UUID) -> SlotOffer | None:
        return self.offers.get(offer_id)

    async def get_unused_by_index(
        self, lead_id: UUID, option_index: int
    ) -> SlotOffer | None:
        matches = [
            offer
            for offer in self.offers.values()
            if offer.lead_id == lead_id
            and offer.option_index == option_index
            and not offer.used
        ]
        if not matches:
            return None
        return matches[0]

    async def persist_booking(
        self,
        *,
        lead_id: UUID,
        offer: SlotOffer,
        idempotency_key: str,
        calendar_event_id: str,
        now: datetime,
    ) -> None:
        if self.fail_outbox_once:
            self.fail_outbox_once = False
            raise OutboxInsertError("outbox insert failed")
        if idempotency_key in self.bookings:
            raise ValueError("duplicate idempotency_key")
        current = self.offers[offer.id]
        self.offers[offer.id] = current.model_copy(update={"used": True})
        self.bookings[idempotency_key] = {
            "lead_id": lead_id,
            "offer_id": offer.id,
            "start": offer.start,
            "status": BookingStatus.confirmed.value,
            "calendar_event_id": calendar_event_id,
            "created_at": now,
        }
        self.outbox.append(
            {
                "lead_id": lead_id,
                "target": "crm",
                "payload": crm_outbox_payload(
                    lead_id=lead_id,
                    offer_id=offer.id,
                    idempotency_key=idempotency_key,
                    calendar_event_id=calendar_event_id,
                ),
                "status": OutboxStatus.pending.value,
                "next_attempt_at": now,
            }
        )
