"""Transactional job queue with skip-locked claims and per-lead advisory locks."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from coaching_inquiry_engine.db.models import JobRow


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(self, lead_id: UUID, inbound_message_id: UUID) -> JobRow:
        job = JobRow(lead_id=lead_id, inbound_message_id=inbound_message_id)
        self._session.add(job)
        await self._session.flush()
        return job

    async def claim_next(self, now: datetime) -> JobRow | None:
        job = await self._session.scalar(
            select(JobRow)
            .where(
                JobRow.status == "queued",
                JobRow.available_at <= now,
            )
            .order_by(JobRow.created_at, JobRow.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None

        lock_id = int.from_bytes(job.lead_id.bytes[:8], "big", signed=True)
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id}
        )
        job.status = "processing"
        job.attempts += 1
        job.claimed_at = now
        await self._session.flush()
        return job

    async def mark_done(self, job_id: UUID, now: datetime) -> None:
        job = await self._session.get(JobRow, job_id)
        if job is None:
            raise KeyError(f"job {job_id} not found")
        job.status = "done"
        job.completed_at = now
        job.claimed_at = None
        job.last_error = None
        await self._session.flush()

    async def mark_failed(
        self,
        job_id: UUID,
        *,
        error: str,
        now: datetime,
        max_attempts: int,
        next_attempt_at: datetime,
    ) -> bool:
        job = await self._session.get(JobRow, job_id)
        if job is None:
            raise KeyError(f"job {job_id} not found")
        job.attempts += 1
        job.last_error = error[:500]
        job.claimed_at = None
        if job.attempts >= max_attempts:
            job.status = "dead"
            job.completed_at = now
            await self._session.flush()
            return True
        job.status = "queued"
        job.available_at = next_attempt_at
        await self._session.flush()
        return False
