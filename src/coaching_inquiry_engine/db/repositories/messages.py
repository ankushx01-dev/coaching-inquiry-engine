"""Message aggregate persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from coaching_inquiry_engine.db.models import MessageRow
from coaching_inquiry_engine.domain.models import MessageDirection


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_message_if_new(
        self,
        provider_message_id: str,
        lead_id: UUID,
        direction: MessageDirection,
        body: str,
        received_at: datetime,
    ) -> bool:
        stmt = (
            insert(MessageRow)
            .values(
                provider_message_id=provider_message_id,
                lead_id=lead_id,
                direction=direction.value,
                body=body,
                received_at=received_at,
            )
            .on_conflict_do_nothing(constraint="uq_messages_provider_message_id")
            .returning(MessageRow.id)
        )
        inserted_id = await self._session.scalar(stmt)
        return inserted_id is not None

    async def get_by_provider_message_id(
        self, provider_message_id: str
    ) -> MessageRow | None:
        return await self._session.scalar(
            select(MessageRow).where(
                MessageRow.provider_message_id == provider_message_id
            )
        )

    async def get_by_id(self, message_id: UUID) -> MessageRow | None:
        return await self._session.get(MessageRow, message_id)

    async def list_recent(self, lead_id: UUID, limit: int = 10) -> list[MessageRow]:
        rows = list(
            await self._session.scalars(
                select(MessageRow)
                .where(MessageRow.lead_id == lead_id)
                .order_by(MessageRow.received_at.desc(), MessageRow.id.desc())
                .limit(limit)
            )
        )
        rows.reverse()
        return rows

    async def list_replies(self, lead_id: UUID) -> list[MessageRow]:
        return list(
            await self._session.scalars(
                select(MessageRow)
                .where(
                    MessageRow.lead_id == lead_id,
                    MessageRow.direction == MessageDirection.outbound.value,
                )
                .order_by(MessageRow.received_at, MessageRow.id)
            )
        )
