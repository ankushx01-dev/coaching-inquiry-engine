"""Dispatch shared outbox rows to CRM and staff alert adapters."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from coaching_inquiry_engine.db.models import OutboxRow
from coaching_inquiry_engine.ports.clock import ClockPort
from coaching_inquiry_engine.ports.crm import CrmPort
from coaching_inquiry_engine.ports.staff_alert import StaffAlertPort
from coaching_inquiry_engine.services.booking_service import CRM_OUTBOX_EVENT
from coaching_inquiry_engine.services.escalation_service import StaffAlertPayload


class OutboxRepositoryPort(Protocol):
    async def claim_pending(self, now: datetime, limit: int) -> list[OutboxRow]: ...

    async def mark_sent(self, row_id: UUID) -> None: ...

    async def mark_failed(
        self,
        row_id: UUID,
        *,
        now: datetime,
        next_attempt_at: datetime,
        max_attempts: int,
        error: str,
    ) -> bool: ...


def outbox_backoff_seconds(base_seconds: float, attempt: int) -> float:
    if base_seconds < 0 or attempt < 1:
        raise ValueError("base_seconds must be non-negative and attempt must be >= 1")
    return base_seconds * (2 ** (attempt - 1))


async def drain_outbox(
    now: datetime,
    crm: CrmPort,
    staff_alerts: StaffAlertPort,
    limit: int,
    *,
    repository: OutboxRepositoryPort,
    clock: ClockPort,
    max_attempts: int = 5,
    base_backoff_seconds: float = 1.0,
) -> int:
    """Claim and dispatch up to *limit* due rows, returning their count."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    rows = await repository.claim_pending(now, limit)
    for row in rows:
        try:
            await _dispatch(row, crm, staff_alerts)
        except Exception as exc:
            failed_at = clock.now()
            delay = outbox_backoff_seconds(base_backoff_seconds, row.attempts)
            await repository.mark_failed(
                row.id,
                now=failed_at,
                next_attempt_at=failed_at + timedelta(seconds=delay),
                max_attempts=max_attempts,
                error=type(exc).__name__,
            )
        else:
            await repository.mark_sent(row.id)
    return len(rows)


async def _dispatch(
    row: OutboxRow,
    crm: CrmPort,
    staff_alerts: StaffAlertPort,
) -> None:
    if row.target == "staff_alert":
        await staff_alerts.send_alert(StaffAlertPayload.model_validate(row.payload))
        return
    if row.target == "crm":
        lead_ref = UUID(str(row.payload["lead_id"]))
        event = str(row.payload.get("event", ""))
        fields = {"source_event": event}
        await crm.upsert_contact(lead_ref, fields)
        if event == CRM_OUTBOX_EVENT:
            await crm.create_deal(lead_ref, stage="booked")
        return
    raise ValueError(f"unsupported outbox target: {row.target}")
