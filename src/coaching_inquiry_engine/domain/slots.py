"""Pure slot generation and booking guards. The caller supplies `now`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from coaching_inquiry_engine.domain.config import BOOKING_STEP_MIN


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Slot(_StrictModel):
    """A bookable window. `start` is timezone-aware UTC."""

    start: datetime
    duration_min: int = Field(gt=0)


class SlotOffer(_StrictModel):
    """Stored offer the LLM may choose only by option_index."""

    id: UUID
    lead_id: UUID
    option_index: int = Field(ge=0, le=2)
    start: datetime
    duration_min: int = Field(gt=0)
    expires_at: datetime
    used: bool


class BookingRejected(Exception):  # noqa: N818
    """A stored offer or generated slot cannot be booked."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def candidate_slots(
    now: datetime,
    tz: ZoneInfo,
    hours: Mapping[int, tuple[time, time]],
    busy: Sequence[tuple[datetime, datetime]],
    duration_min: int,
    days: int,
    limit: int,
    *,
    lead_min: int,
    buffer_min: int,
    step_min: int = BOOKING_STEP_MIN,
) -> list[Slot]:
    """Return up to `limit` earliest slots that fit hours, lead time, and busy."""
    if duration_min <= 0 or days <= 0 or limit <= 0 or step_min <= 0:
        return []
    now_utc = _aware_utc(now)
    local_now = now_utc.astimezone(tz)
    earliest = now_utc + timedelta(minutes=lead_min)
    busy_utc = [(_aware_utc(start), _aware_utc(end)) for start, end in busy]
    found: list[Slot] = []
    for day_offset in range(days):
        day = local_now.date() + timedelta(days=day_offset)
        window = hours.get(day.weekday())
        if window is None:
            continue
        open_time, close_time = window
        cursor = datetime.combine(day, open_time, tzinfo=tz)
        close_at = datetime.combine(day, close_time, tzinfo=tz)
        duration = timedelta(minutes=duration_min)
        step = timedelta(minutes=step_min)
        while cursor + duration <= close_at:
            start_utc = cursor.astimezone(UTC)
            slot = Slot(start=start_utc, duration_min=duration_min)
            if start_utc >= earliest and _is_free(slot, busy_utc, buffer_min):
                found.append(slot)
                if len(found) >= limit:
                    return found
            cursor += step
    return found


def validate_booking(
    slot: Slot,
    *,
    now: datetime,
    tz: ZoneInfo,
    hours: Mapping[int, tuple[time, time]],
    busy: Sequence[tuple[datetime, datetime]],
    lead_min: int,
    buffer_min: int,
) -> None:
    """Raise BookingRejected with slot_taken or slot_invalid."""
    try:
        start_utc = _aware_utc(slot.start)
        now_utc = _aware_utc(now)
    except ValueError as exc:
        raise BookingRejected("slot_invalid") from exc
    if slot.duration_min <= 0:
        raise BookingRejected("slot_invalid")
    if start_utc < now_utc + timedelta(minutes=lead_min):
        raise BookingRejected("slot_invalid")
    local_start = start_utc.astimezone(tz)
    window = hours.get(local_start.weekday())
    if window is None:
        raise BookingRejected("slot_invalid")
    open_time, close_time = window
    local_end = local_start + timedelta(minutes=slot.duration_min)
    if local_start.time() < open_time:
        raise BookingRejected("slot_invalid")
    close_at = datetime.combine(local_start.date(), close_time, tzinfo=tz)
    if local_end > close_at:
        raise BookingRejected("slot_invalid")
    busy_utc = [(_aware_utc(start), _aware_utc(end)) for start, end in busy]
    if not _is_free(slot, busy_utc, buffer_min):
        raise BookingRejected("slot_taken")


def assert_offer_bookable(
    offer: SlotOffer | None, *, lead_id: UUID, now: datetime
) -> SlotOffer:
    """Reject missing, foreign, used, or expired offers with a reason code."""
    if offer is None:
        raise BookingRejected("offer_not_found")
    if offer.lead_id != lead_id:
        raise BookingRejected("offer_wrong_lead")
    if offer.used:
        raise BookingRejected("offer_used")
    if _aware_utc(offer.expires_at) <= _aware_utc(now):
        raise BookingRejected("offer_expired")
    return offer


def format_slot_label(start: datetime, tz: ZoneInfo) -> str:
    """System-generated label. This is the only time text the LLM may see."""
    local = _aware_utc(start).astimezone(tz)
    clock = local.strftime("%I:%M %p").lstrip("0")
    zone = local.tzname() or "UTC"
    return f"{local.strftime('%A')} {local.day} {local.strftime('%b')}, {clock} {zone}"


def _is_free(
    slot: Slot,
    busy: Sequence[tuple[datetime, datetime]],
    buffer_min: int,
) -> bool:
    buffer = timedelta(minutes=buffer_min)
    slot_start = _aware_utc(slot.start)
    slot_end = slot_start + timedelta(minutes=slot.duration_min)
    for busy_start, busy_end in busy:
        blocked_start = busy_start - buffer
        blocked_end = busy_end + buffer
        if slot_start < blocked_end and slot_end > blocked_start:
            return False
    return True


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)
