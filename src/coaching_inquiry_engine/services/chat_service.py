"""Chat ingress use cases. HTTP handlers delegate to this service."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from coaching_inquiry_engine.domain.quick_replies import QuickReply
from coaching_inquiry_engine.ports.chat_store import ChatStorePort, StoredChatMessage
from coaching_inquiry_engine.ports.rate_limiter import RateLimiterPort


class RateLimitExceededError(Exception):
    """The session or source IP exceeded its configured request limit."""


@dataclass(frozen=True, slots=True)
class AcceptedChatMessage:
    accepted: bool
    message_id: UUID


class ChatMessageService:
    def __init__(
        self,
        store: ChatStorePort,
        rate_limiter: RateLimiterPort,
        quick_replies: tuple[QuickReply, ...] = (),
    ) -> None:
        self._store = store
        self._rate_limiter = rate_limiter
        self.quick_replies = quick_replies

    async def submit(
        self,
        *,
        session_id: str,
        client_message_id: str,
        text: str,
        consent_given: bool,
        ip_address: str,
    ) -> AcceptedChatMessage:
        if not self._rate_limiter.allow(session_id, ip_address):
            raise RateLimitExceededError
        message_id = await self._store.accept_message(
            session_id=session_id,
            client_message_id=client_message_id,
            text=text,
            consent_given=consent_given,
        )
        return AcceptedChatMessage(accepted=True, message_id=message_id)

    async def messages(self, *, session_id: str) -> list[StoredChatMessage]:
        messages = await self._store.list_messages(session_id)
        return sorted(
            messages,
            key=lambda message: (message.received_at, message.message_id),
        )
