"""PostgreSQL implementation of the chat persistence port."""

from __future__ import annotations

from datetime import UTC
from hashlib import sha256
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from coaching_inquiry_engine.adapters.clock import SystemClock
from coaching_inquiry_engine.db.encryption import ContactCipher
from coaching_inquiry_engine.db.repositories.audits import AuditRepository
from coaching_inquiry_engine.db.repositories.consents import ConsentRepository
from coaching_inquiry_engine.db.repositories.jobs import JobRepository
from coaching_inquiry_engine.db.repositories.leads import LeadRepository
from coaching_inquiry_engine.db.repositories.messages import MessageRepository
from coaching_inquiry_engine.domain.models import ContactChannel, MessageDirection
from coaching_inquiry_engine.logging import mask_contact_text
from coaching_inquiry_engine.ports.chat_store import StoredChatMessage
from coaching_inquiry_engine.ports.clock import ClockPort
from coaching_inquiry_engine.services.consent_service import ConsentService


def session_lookup_key(session_id: str) -> str:
    """Return a stable database key without persisting the bearer token."""
    return sha256(session_id.encode("utf-8")).hexdigest()


def idempotency_key(session_id: str, client_message_id: str) -> str:
    material = f"{session_id}\0{client_message_id}".encode()
    return "chat-" + sha256(material).hexdigest()


class PostgresChatStore:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cipher: ContactCipher,
        clock: ClockPort | None = None,
    ) -> None:
        self._sessions = sessions
        self._cipher = cipher
        self._clock = clock or SystemClock()

    async def accept_message(
        self,
        *,
        session_id: str,
        client_message_id: str,
        text: str,
        consent_given: bool,
    ) -> UUID:
        session_key = session_lookup_key(session_id)
        provider_id = idempotency_key(session_id, client_message_id)
        now = self._clock.now()
        async with self._sessions() as session:
            async with session.begin():
                lead_repo = LeadRepository(session, self._cipher)
                lead = await lead_repo.get_or_create_lead(
                    ContactChannel.chat, session_key
                )
                messages = MessageRepository(session)
                inserted = await messages.insert_message_if_new(
                    provider_id,
                    lead.id,
                    MessageDirection.inbound,
                    mask_contact_text(text),
                    now,
                )
                row = await messages.get_by_provider_message_id(provider_id)
                if row is None:
                    raise RuntimeError("accepted message row was not found")

                if inserted:
                    if consent_given:
                        consents = ConsentRepository(session)
                        if not await consents.latest_consent_granted(
                            lead.id, ContactChannel.chat
                        ):
                            await ConsentService(
                                consents, AuditRepository(session)
                            ).record_and_audit(
                                lead.id,
                                ContactChannel.chat,
                                "chat-api-v1",
                            )
                    await JobRepository(session).enqueue(lead.id, row.id)
                return row.id

    async def list_messages(self, session_id: str) -> list[StoredChatMessage]:
        session_key = session_lookup_key(session_id)
        async with self._sessions() as session:
            lead = await LeadRepository(
                session, self._cipher
            ).get_by_channel_external_user(ContactChannel.chat, session_key)
            if lead is None:
                return []
            rows = await MessageRepository(session).list_chat_messages(lead.id)
            return [
                StoredChatMessage(
                    message_id=row.id,
                    direction=MessageDirection(row.direction),
                    text=row.body,
                    received_at=row.received_at.astimezone(UTC),
                )
                for row in rows
            ]

    async def conversation_context(self, session_id: str) -> dict[str, object] | None:
        session_key = session_lookup_key(session_id)
        async with self._sessions() as session:
            lead = await LeadRepository(
                session, self._cipher
            ).get_by_channel_external_user(ContactChannel.chat, session_key)
            if lead is None:
                return None
            return await LeadRepository(session, self._cipher).get_conversation_context(
                lead.id
            )
