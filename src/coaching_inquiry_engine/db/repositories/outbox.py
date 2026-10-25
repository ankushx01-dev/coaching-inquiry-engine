"""Shared transactional outbox persistence and delivery claims."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from coaching_inquiry_engine.db.models import OutboxRow
from coaching_inquiry_engine.db.repositories.audits import AuditRepository
from coaching_inquiry_engine.domain.models import OutboxStatus


class OutboxRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    async def enqueue_in_session(
        session: AsyncSession,
        *,
        lead_id: UUID,
        target: str,
        payload: dict[str, object],
        available_at: datetime,
    ) -> OutboxRow:
        row = OutboxRow(
            lead_id=lead_id,
            target=target,
            payload=payload,
            attempts=0,
            status=OutboxStatus.pending.value,
            next_attempt_at=available_at,
        )
        session.add(row)
        await session.flush()
        return row

    async def claim_pending(self, now: datetime, limit: int) -> list[OutboxRow]:
        async with self._sessions() as session:
            async with session.begin():
                rows = list(
                    await session.scalars(
                        select(OutboxRow)
                        .where(
                            OutboxRow.status == OutboxStatus.pending.value,
                            OutboxRow.next_attempt_at <= now,
                        )
                        .order_by(OutboxRow.next_attempt_at, OutboxRow.id)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                for row in rows:
                    row.status = OutboxStatus.processing.value
                    row.attempts += 1
                    row.claimed_at = now
                await session.flush()
            for row in rows:
                session.expunge(row)
            return rows

    async def mark_sent(self, row_id: UUID) -> None:
        async with self._sessions() as session:
            async with session.begin():
                row = await session.get(OutboxRow, row_id)
                if row is None:
                    raise KeyError(f"outbox row {row_id} not found")
                row.status = OutboxStatus.sent.value
                row.claimed_at = None
                row.last_error = None

    async def mark_failed(
        self,
        row_id: UUID,
        *,
        now: datetime,
        next_attempt_at: datetime,
        max_attempts: int,
        error: str,
    ) -> bool:
        async with self._sessions() as session:
            async with session.begin():
                row = await session.get(OutboxRow, row_id)
                if row is None:
                    raise KeyError(f"outbox row {row_id} not found")
                row.claimed_at = None
                row.last_error = error[:300]
                if row.attempts >= max_attempts:
                    row.status = OutboxStatus.dead.value
                    await AuditRepository(session).append_audit_event(
                        lead_id=row.lead_id,
                        event_type="outbox_delivery_dead",
                        detail={
                            "outbox_id": str(row.id),
                            "target": row.target,
                            "error": error[:100],
                            "attempts": row.attempts,
                        },
                    )
                    return True
                row.status = OutboxStatus.pending.value
                row.next_attempt_at = next_attempt_at
                return False

