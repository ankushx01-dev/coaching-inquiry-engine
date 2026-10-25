"""Persistence port for chat message acceptance and reply retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StoredChatReply:
    message_id: UUID
    text: str


class ChatStorePort(Protocol):
    async def accept_message(
        self,
        *,
        session_id: str,
        client_message_id: str,
        text: str,
        consent_given: bool,
    ) -> UUID: ...

    async def list_replies(self, session_id: str) -> list[StoredChatReply]: ...
