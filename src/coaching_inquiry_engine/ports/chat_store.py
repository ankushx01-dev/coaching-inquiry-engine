"""Persistence port for chat message acceptance and reply retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from coaching_inquiry_engine.domain.models import MessageDirection


@dataclass(frozen=True, slots=True)
class StoredChatMessage:
    message_id: UUID
    direction: MessageDirection
    text: str
    received_at: datetime


class ChatStorePort(Protocol):
    async def accept_message(
        self,
        *,
        session_id: str,
        client_message_id: str,
        text: str,
        consent_given: bool,
    ) -> UUID: ...

    async def list_messages(self, session_id: str) -> list[StoredChatMessage]: ...

    async def conversation_context(
        self, session_id: str
    ) -> dict[str, object] | None: ...
