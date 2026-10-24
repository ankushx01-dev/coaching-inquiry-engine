"""Audit event persistence. Append-only; no update or delete methods."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from coaching_inquiry_engine.db.audit import assert_safe_audit_detail
from coaching_inquiry_engine.db.models import AuditEventRow


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_audit_event(
        self,
        lead_id: UUID | None,
        event_type: str,
        detail: Mapping[str, object],
        prompt_version: str | None = None,
    ) -> None:
        assert_safe_audit_detail(detail)
        self._session.add(
            AuditEventRow(
                lead_id=lead_id,
                event_type=event_type,
                detail=dict(detail),
                prompt_version=prompt_version,
            )
        )
        await self._session.flush()
