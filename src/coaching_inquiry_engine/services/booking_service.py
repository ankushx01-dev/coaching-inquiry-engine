"""Create slot offers and book by stored offer index. The LLM never picks a time."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, time, timedelta
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from coaching_inquiry_engine.domain.config import (
    BOOKING_BUFFER_MIN,
    BOOKING_DAYS,
    BOOKING_DURATION_MIN,
    BOOKING_LEAD_MIN,
    BOOKING_OFFER_LIMIT,
    BOOKING_OFFER_TTL_MIN,
    BOOKING_TZ,
    BUSINESS_HOURS,
)
from coaching_inquiry_engine.domain.decisions import (
    AgentDecision,
    SlotOption,
    booking_choice_index,
)
from coaching_inquiry_engine.domain.models import BookingStatus, OutboxStatus
from coaching_inquiry_engine.domain.slots import (
    BookingRejected,
    Slot,
    SlotOffer,
    assert_offer_bookable,
    candidate_slots,
    format_slot_label,
    validate_booking,
)
from coaching_inquiry_engine.ports.calendar import CalendarPort

_CALENDAR_TITLE = "Counselling"
_TEXT_BY_REASON: Mapping[str, str] = {
    "offer_expired": "offer_expired",
    "offer_not_found": "slot_invalid",
    "offer_wrong_lead": "slot_invalid",
    "offer_used": "slot_invalid",
    "slot_taken": "slot_taken",
    "slot_invalid": "slot_invalid",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OfferDraft(_StrictModel):
    option_index: int
    start: datetime
    duration_min: int
    expires_at: datetime


class BookingResult(_StrictModel):
    ok: bool
    status: str
    text_key: str
    reason: str | None = None
    calendar_event_id: str | None = None
    label: str | None = None


class BookingStore(Protocol):
    async def replace_active_offers(
        self, lead_id: UUID, drafts: list[OfferDraft]
    ) -> list[SlotOffer]: ...

    async def get_offer(self, offer_id: UUID) -> SlotOffer | None: ...

    async def get_unused_by_index(
        self, lead_id: UUID, option_index: int
    ) -> SlotOffer | None: ...

    async def persist_booking(
        self,
        *,
        lead_id: UUID,
        offer: SlotOffer,
        idempotency_key: str,
        calendar_event_id: str,
        now: datetime,
    ) -> None: ...


class BookingService:
    def __init__(
        self,
        calendar: CalendarPort,
        store: BookingStore,
        *,
        tz: ZoneInfo = BOOKING_TZ,
        hours: Mapping[int, tuple[time, time]] = BUSINESS_HOURS,
        duration_min: int = BOOKING_DURATION_MIN,
        days: int = BOOKING_DAYS,
        limit: int = BOOKING_OFFER_LIMIT,
        lead_min: int = BOOKING_LEAD_MIN,
        buffer_min: int = BOOKING_BUFFER_MIN,
        offer_ttl_min: int = BOOKING_OFFER_TTL_MIN,
    ) -> None:
        self._calendar = calendar
        self._store = store
        self._tz = tz
        self._hours = hours
        self._duration_min = duration_min
        self._days = days
        self._limit = limit
        self._lead_min = lead_min
        self._buffer_min = buffer_min
        self._offer_ttl_min = offer_ttl_min

    async def create_offers(self, lead_id: UUID, now: datetime) -> list[SlotOption]:
        now_utc = _aware_utc(now)
        busy = self._calendar.busy_intervals(
            now_utc, now_utc + timedelta(days=self._days)
        )
        slots = candidate_slots(
            now_utc,
            self._tz,
            self._hours,
            busy,
            self._duration_min,
            self._days,
            self._limit,
            lead_min=self._lead_min,
            buffer_min=self._buffer_min,
        )
        expires_at = now_utc + timedelta(minutes=self._offer_ttl_min)
        drafts = [
            OfferDraft(
                option_index=index,
                start=slot.start,
                duration_min=slot.duration_min,
                expires_at=expires_at,
            )
            for index, slot in enumerate(slots)
        ]
        stored = await self._store.replace_active_offers(lead_id, drafts)
        return [
            SlotOption(
                index=offer.option_index,
                label=format_slot_label(offer.start, self._tz),
            )
            for offer in stored
        ]

    async def book_from_decision(
        self, lead_id: UUID, decision: AgentDecision, now: datetime
    ) -> BookingResult:
        index = booking_choice_index(decision)
        if index is None:
            return _rejected("offer_not_found")
        return await self.book_offer(lead_id, index, now)

    async def book_offer(
        self, lead_id: UUID, offer_index_or_id: int | UUID, now: datetime
    ) -> BookingResult:
        try:
            offer = await self._load_offer(lead_id, offer_index_or_id)
            assert_offer_bookable(offer, lead_id=lead_id, now=now)
            now_utc = _aware_utc(now)
            busy = self._calendar.busy_intervals(
                now_utc, now_utc + timedelta(days=self._days)
            )
            slot = Slot(start=offer.start, duration_min=offer.duration_min)
            validate_booking(
                slot,
                now=now_utc,
                tz=self._tz,
                hours=self._hours,
                busy=busy,
                lead_min=self._lead_min,
                buffer_min=self._buffer_min,
            )
            idempotency_key = f"{lead_id}:{offer.id}"
            event_id = self._calendar.create_event(
                idempotency_key,
                slot.start,
                slot.duration_min,
                _CALENDAR_TITLE,
            )
            await self._store.persist_booking(
                lead_id=lead_id,
                offer=offer,
                idempotency_key=idempotency_key,
                calendar_event_id=event_id,
                now=now_utc,
            )
        except BookingRejected as exc:
            return _rejected(exc.reason)
        return BookingResult(
            ok=True,
            status=BookingStatus.confirmed.value,
            text_key="booking_confirmed",
            calendar_event_id=event_id,
            label=format_slot_label(offer.start, self._tz),
        )


    async def _load_offer(
        self, lead_id: UUID, offer_index_or_id: int | UUID
    ) -> SlotOffer | None:
        if isinstance(offer_index_or_id, UUID):
            return await self._store.get_offer(offer_index_or_id)
        return await self._store.get_unused_by_index(lead_id, offer_index_or_id)


def _rejected(reason: str) -> BookingResult:
    return BookingResult(
        ok=False,
        status="rejected",
        reason=reason,
        text_key=_TEXT_BY_REASON.get(reason, "slot_invalid"),
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


# Imported by stores that write the CRM outbox row.
CRM_OUTBOX_TARGET = "crm"
CRM_OUTBOX_EVENT = "booking_confirmed"


def crm_outbox_payload(
    *,
    lead_id: UUID,
    offer_id: UUID,
    idempotency_key: str,
    calendar_event_id: str,
) -> dict[str, str]:
    return {
        "event": CRM_OUTBOX_EVENT,
        "lead_id": str(lead_id),
        "offer_id": str(offer_id),
        "idempotency_key": idempotency_key,
        "calendar_event_id": calendar_event_id,
        "status": OutboxStatus.pending.value,
    }
