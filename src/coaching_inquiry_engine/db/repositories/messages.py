"""Message aggregate persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

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
