"""Deterministic clock, retry scheduling, expiry, and clock-call guard tests."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from coaching_inquiry_engine.adapters.booking_memory import MemoryBookingStore
from coaching_inquiry_engine.adapters.calendar_fake import FakeCalendar
from coaching_inquiry_engine.adapters.clock_fake import FakeClock
from coaching_inquiry_engine.services.booking_service import BookingService
from coaching_inquiry_engine.services.job_retry import retry_at


def test_fake_clock_can_be_set_and_advanced() -> None:
    initial = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    clock = FakeClock(initial)
    assert clock.now() == initial
    assert clock.advance(timedelta(seconds=5)) == initial + timedelta(seconds=5)

    later = initial + timedelta(hours=1)
    clock.set(later)
    assert clock.now() == later


async def test_retry_schedule_uses_fake_clock_without_sleeping() -> None:
    clock = FakeClock(datetime(2026, 10, 25, 12, 0, tzinfo=UTC))
    scheduled = retry_at(clock.now(), attempt=3)
    assert scheduled == clock.now() + timedelta(seconds=4)


async def test_offer_expiry_uses_fake_clock_without_sleeping() -> None:
    clock = FakeClock(datetime(2026, 10, 26, 8, 0, tzinfo=UTC))
    store = MemoryBookingStore()
    service = BookingService(FakeCalendar(), store)
    lead_id = uuid4()
    await service.create_offers(lead_id, clock.now())

    clock.advance(timedelta(minutes=31))
    result = await service.book_offer(lead_id, 0, clock.now())

    assert result.ok is False
    assert result.reason == "offer_expired"


def test_production_clock_reads_are_confined_to_system_clock_adapter() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src"
    hits: list[str] = []
    for path in source_root.rglob("*.py"):
        relative = path.relative_to(source_root).as_posix()
        if relative == "coaching_inquiry_engine/adapters/clock.py":
            continue
        if re.search(r"datetime\.now\s*\(|time\.time\s*\(", path.read_text()):
            hits.append(relative)
    assert hits == []
