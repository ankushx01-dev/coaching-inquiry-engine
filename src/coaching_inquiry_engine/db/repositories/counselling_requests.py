"""Counselling request persistence and privacy-safe list projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from coaching_inquiry_engine.db.models import CounsellingRequestRow, LeadRow
from coaching_inquiry_engine.domain.counselling import CounsellingRequestStatus


@dataclass(frozen=True, slots=True)
class CounsellingRequestListItem:
    request_id: UUID
    lead_id: UUID
    first_name: str | None
    exam_id: str | None
    eligibility_status: str | None
    status: CounsellingRequestStatus
    assigned_to: str | None
    created_at: datetime


class CounsellingRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_or_get_open(
        self, lead_id: UUID
    ) -> tuple[CounsellingRequestRow, bool]:
        """Create one open request, using the partial unique index for races."""
        stmt = (
            insert(CounsellingRequestRow)
            .values(lead_id=lead_id, status=CounsellingRequestStatus.new.value)
            .on_conflict_do_nothing(
                index_elements=[CounsellingRequestRow.lead_id],
                index_where=(CounsellingRequestRow.status != "closed"),
            )
            .returning(CounsellingRequestRow.id)
        )
        created_id = await self._session.scalar(stmt)
        if created_id is not None:
            row = await self._session.get(CounsellingRequestRow, created_id)
            if row is None:
                raise RuntimeError("counselling request missing after insert")
            return row, True
        row = await self._session.scalar(
            select(CounsellingRequestRow).where(
                CounsellingRequestRow.lead_id == lead_id,
                CounsellingRequestRow.status != CounsellingRequestStatus.closed.value,
            )
        )
        if row is None:
            raise RuntimeError("open counselling request missing after conflict")
        return row, False

    async def get_with_lead(
        self, request_id: UUID
    ) -> tuple[CounsellingRequestRow, LeadRow] | None:
        result = await self._session.execute(
            select(CounsellingRequestRow, LeadRow)
            .join(LeadRow, LeadRow.id == CounsellingRequestRow.lead_id)
            .where(CounsellingRequestRow.id == request_id)
        )
        row = result.one_or_none()
        return (row[0], row[1]) if row is not None else None

    async def list_page(
        self,
        *,
        exam_id: str | None,
        status: CounsellingRequestStatus | None,
        date_from: date | None,
        date_to: date | None,
        page: int,
        page_size: int = 25,
    ) -> tuple[list[CounsellingRequestListItem], int]:
        filters = []
        if exam_id is not None:
            filters.append(LeadRow.exam_id == exam_id)
        if status is not None:
            filters.append(CounsellingRequestRow.status == status.value)
        if date_from is not None:
            filters.append(
                CounsellingRequestRow.created_at
                >= datetime.combine(date_from, time.min, UTC)
            )
        if date_to is not None:
            filters.append(
                CounsellingRequestRow.created_at
                < datetime.combine(date_to + timedelta(days=1), time.min, UTC)
            )

        count_stmt = (
            select(func.count())
            .select_from(CounsellingRequestRow)
            .join(LeadRow, LeadRow.id == CounsellingRequestRow.lead_id)
            .where(*filters)
        )
        total = int(await self._session.scalar(count_stmt) or 0)
        stmt = (
            select(
                CounsellingRequestRow.id,
                CounsellingRequestRow.lead_id,
                LeadRow.name,
                LeadRow.exam_id,
                LeadRow.eligibility_status,
                CounsellingRequestRow.status,
                CounsellingRequestRow.assigned_to,
                CounsellingRequestRow.created_at,
            )
            .join(LeadRow, LeadRow.id == CounsellingRequestRow.lead_id)
            .where(*filters)
            .order_by(
                CounsellingRequestRow.created_at.desc(),
                CounsellingRequestRow.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = await self._session.execute(stmt)
        items = [
            CounsellingRequestListItem(
                request_id=request_id,
                lead_id=lead_id,
                first_name=_first_name(name),
                exam_id=exam_id,
                eligibility_status=eligibility_status,
                status=CounsellingRequestStatus(status_value),
                assigned_to=assigned_to,
                created_at=created_at,
            )
            for (
                request_id,
                lead_id,
                name,
                exam_id,
                eligibility_status,
                status_value,
                assigned_to,
                created_at,
            ) in rows
        ]
        return items, total

    async def update(
        self,
        request_id: UUID,
        *,
        status: CounsellingRequestStatus,
        assigned_to: str | None,
        notes: str | None,
        now: datetime,
    ) -> CounsellingRequestRow | None:
        row = await self._session.scalar(
            select(CounsellingRequestRow)
            .where(CounsellingRequestRow.id == request_id)
            .with_for_update()
        )
        if row is None:
            return None
        row.status = status.value
        row.assigned_to = assigned_to
        row.notes = notes
        row.updated_at = now
        await self._session.flush()
        return row


def _first_name(name: str | None) -> str | None:
    if name is None:
        return None
    return name.strip().split(maxsplit=1)[0] or None
