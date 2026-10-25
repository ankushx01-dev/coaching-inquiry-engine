"""PostgreSQL integration tests for shared outbox locking and dead letters."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from coaching_inquiry_engine.adapters.clock_fake import FakeClock
from coaching_inquiry_engine.adapters.crm_fake import FakeCrm
from coaching_inquiry_engine.adapters.staff_alert_fake import FakeStaffAlert
from coaching_inquiry_engine.db.models import AuditEventRow, OutboxRow
from coaching_inquiry_engine.db.repositories.leads import LeadRepository
from coaching_inquiry_engine.db.repositories.outbox import OutboxRepository
from coaching_inquiry_engine.domain.models import ContactChannel, OutboxStatus
from coaching_inquiry_engine.services.outbox_service import drain_outbox

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


async def _add_outbox_row(
    session: AsyncSession,
    *,
    cipher: object,
    external_user_id: str,
) -> UUID:
    lead = await LeadRepository(session, cipher).get_or_create_lead(
        ContactChannel.chat, external_user_id
    )
    row = await OutboxRepository.enqueue_in_session(
        session,
        lead_id=lead.id,
        target="crm",
        payload={"lead_id": str(lead.id), "event": "contact_updated"},
        available_at=_NOW,
    )
    return row.id


async def test_concurrent_drains_claim_disjoint_rows(
    session: AsyncSession,
    engine: AsyncEngine,
    cipher: object,
) -> None:
    await _add_outbox_row(session, cipher=cipher, external_user_id="outbox-a")
    await _add_outbox_row(session, cipher=cipher, external_user_id="outbox-b")
    await session.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    first_started = asyncio.Event()
    both_started = asyncio.Event()
    release = asyncio.Event()

    class CoordinatedCrm:
        def __init__(self) -> None:
            self.lead_refs: list[UUID] = []

        async def upsert_contact(self, lead_ref: UUID, fields: object) -> None:
            _ = fields
            self.lead_refs.append(lead_ref)
            if len(self.lead_refs) == 1:
                first_started.set()
            if len(self.lead_refs) == 2:
                both_started.set()
            await release.wait()

        async def create_deal(self, lead_ref: UUID, stage: str) -> None:
            _ = lead_ref, stage

    crm = CoordinatedCrm()
    repository = OutboxRepository(sessions)
    clock = FakeClock(_NOW)
    first = asyncio.create_task(
        drain_outbox(
            _NOW, crm, FakeStaffAlert(), 1,
            repository=repository, clock=clock,
        )
    )
    await first_started.wait()
    second = asyncio.create_task(
        drain_outbox(
            _NOW, crm, FakeStaffAlert(), 1,
            repository=repository, clock=clock,
        )
    )
    await asyncio.wait_for(both_started.wait(), timeout=5)
    assert len(crm.lead_refs) == 2
    assert len(set(crm.lead_refs)) == 2
    release.set()
    await asyncio.gather(first, second)


async def test_dead_status_and_audit_event_persist(
    session: AsyncSession,
    engine: AsyncEngine,
    cipher: object,
) -> None:
    row_id = await _add_outbox_row(
        session, cipher=cipher, external_user_id="outbox-dead"
    )
    await session.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    clock = FakeClock(_NOW)
    repository = OutboxRepository(sessions)
    crm = FakeCrm(fail_times=5)

    for _ in range(5):
        await drain_outbox(
            clock.now(), crm, FakeStaffAlert(), 1,
            repository=repository, clock=clock, max_attempts=5,
            base_backoff_seconds=2,
        )
        async with sessions() as verify_session:
            row = await verify_session.get(OutboxRow, row_id)
            assert row is not None
            if row.status == OutboxStatus.pending.value:
                clock.set(row.next_attempt_at)

    async with sessions() as verify_session:
        row = await verify_session.get(OutboxRow, row_id)
        audit_count = await verify_session.scalar(
            select(func.count())
            .select_from(AuditEventRow)
            .where(
                AuditEventRow.lead_id == row.lead_id if row is not None else False,
                AuditEventRow.event_type == "outbox_delivery_dead",
            )
        )
        assert row is not None
        assert row.status == OutboxStatus.dead.value
        assert row.attempts == 5
        assert audit_count == 1
