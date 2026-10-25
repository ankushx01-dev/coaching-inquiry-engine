"""Outbox dispatch behavior with deterministic in-memory rows and adapters."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from coaching_inquiry_engine.adapters.clock_fake import FakeClock
from coaching_inquiry_engine.adapters.crm_fake import FakeCrm
from coaching_inquiry_engine.adapters.staff_alert_fake import FakeStaffAlert
from coaching_inquiry_engine.db.models import OutboxRow
from coaching_inquiry_engine.domain.models import OutboxStatus
from coaching_inquiry_engine.services.outbox_service import (
    drain_outbox,
    outbox_backoff_seconds,
)

_LEAD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _row(now: datetime, *, target: str = "crm", lead_id: UUID = _LEAD_ID) -> OutboxRow:
    return OutboxRow(
        id=uuid4(),
        lead_id=lead_id,
        target=target,
        payload={"lead_id": str(lead_id), "event": "contact_updated"},
        attempts=0,
        status=OutboxStatus.pending.value,
        next_attempt_at=now,
    )


class _MemoryOutboxRepository:
    def __init__(self, rows: list[OutboxRow]) -> None:
        self.rows = {row.id: row for row in rows}
        self.audit_events: list[dict[str, object]] = []
        self.claimed_ids: list[UUID] = []
        self.lock = asyncio.Lock()

    async def claim_pending(self, now: datetime, limit: int) -> list[OutboxRow]:
        async with self.lock:
            rows = sorted(
                (
                    row
                    for row in self.rows.values()
                    if row.status == OutboxStatus.pending.value
                    and row.next_attempt_at <= now
                ),
                key=lambda row: (row.next_attempt_at, row.id),
            )[:limit]
            for row in rows:
                row.status = OutboxStatus.processing.value
                row.attempts += 1
                row.claimed_at = now
                self.claimed_ids.append(row.id)
            return rows

    async def mark_sent(self, row_id: UUID) -> None:
        row = self.rows[row_id]
        row.status = OutboxStatus.sent.value
        row.claimed_at = None

    async def mark_failed(
        self,
        row_id: UUID,
        *,
        now: datetime,
        next_attempt_at: datetime,
        max_attempts: int,
        error: str,
    ) -> bool:
        row = self.rows[row_id]
        row.claimed_at = None
        row.last_error = error
        if row.attempts >= max_attempts:
            row.status = OutboxStatus.dead.value
            self.audit_events.append(
                {
                    "outbox_id": str(row_id),
                    "target": row.target,
                    "attempts": row.attempts,
                }
            )
            return True
        row.status = OutboxStatus.pending.value
        row.next_attempt_at = next_attempt_at
        return False


async def test_pending_row_is_dispatched_and_marked_sent() -> None:
    now = datetime(2026, 10, 25, tzinfo=UTC)
    row = _row(now)
    repository = _MemoryOutboxRepository([row])
    crm = FakeCrm()

    count = await drain_outbox(
        now,
        crm,
        FakeStaffAlert(),
        10,
        repository=repository,
        clock=FakeClock(now),
    )

    assert count == 1
    assert row.status == OutboxStatus.sent.value
    assert row.attempts == 1
    assert crm.upsert_calls == [(_LEAD_ID, {"source_event": "contact_updated"})]


async def test_booking_crm_row_upserts_contact_and_creates_deal() -> None:
    now = datetime(2026, 10, 25, tzinfo=UTC)
    row = _row(now)
    row.payload = {
        "lead_id": str(_LEAD_ID),
        "event": "booking_confirmed",
        "offer_id": "offer-1",
    }
    repository = _MemoryOutboxRepository([row])
    crm = FakeCrm()

    await drain_outbox(
        now, crm, FakeStaffAlert(), 1,
        repository=repository, clock=FakeClock(now),
    )

    assert crm.contacts[_LEAD_ID] == {"source_event": "booking_confirmed"}
    assert crm.deals == [(_LEAD_ID, "booked")]


async def test_crm_failing_twice_then_succeeding_records_three_attempts() -> None:
    clock = FakeClock(datetime(2026, 10, 25, tzinfo=UTC))
    row = _row(clock.now())
    repository = _MemoryOutboxRepository([row])
    crm = FakeCrm(fail_times=2)

    for _ in range(3):
        await drain_outbox(
            clock.now(), crm, FakeStaffAlert(), 1,
            repository=repository, clock=clock, base_backoff_seconds=3,
        )
        if row.status == OutboxStatus.pending.value:
            clock.set(row.next_attempt_at)

    assert row.status == OutboxStatus.sent.value
    assert row.attempts == 3
    assert len(crm.upsert_calls) == 1


async def test_five_failures_dead_letter_and_record_one_audit_event() -> None:
    clock = FakeClock(datetime(2026, 10, 25, tzinfo=UTC))
    row = _row(clock.now())
    repository = _MemoryOutboxRepository([row])
    crm = FakeCrm(fail_times=5)

    for _ in range(5):
        await drain_outbox(
            clock.now(), crm, FakeStaffAlert(), 1,
            repository=repository, clock=clock, max_attempts=5,
        )
        if row.status == OutboxStatus.pending.value:
            clock.set(row.next_attempt_at)

    assert row.status == OutboxStatus.dead.value
    assert row.attempts == 5
    assert repository.audit_events == [
        {"outbox_id": str(row.id), "target": "crm", "attempts": 5}
    ]


def test_outbox_backoff_doubles_from_configured_base() -> None:
    assert [outbox_backoff_seconds(3, attempt) for attempt in range(1, 6)] == [
        3,
        6,
        12,
        24,
        48,
    ]


async def test_two_drains_do_not_process_one_row_twice() -> None:
    now = datetime(2026, 10, 25, tzinfo=UTC)
    row = _row(now)
    repository = _MemoryOutboxRepository([row])
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingCrm(FakeCrm):
        async def upsert_contact(self, lead_ref: UUID, fields: object) -> None:
            self.upsert_calls.append((lead_ref, dict(fields)))  # type: ignore[arg-type]
            entered.set()
            await release.wait()

    crm = BlockingCrm()
    first = asyncio.create_task(
        drain_outbox(
            now, crm, FakeStaffAlert(), 1, repository=repository,
            clock=FakeClock(now),
        )
    )
    await entered.wait()
    second_count = await drain_outbox(
        now, crm, FakeStaffAlert(), 1, repository=repository,
        clock=FakeClock(now),
    )
    release.set()
    await first

    assert second_count == 0
    assert repository.claimed_ids == [row.id]
    assert row.status == OutboxStatus.sent.value
    assert len(crm.upsert_calls) == 1

