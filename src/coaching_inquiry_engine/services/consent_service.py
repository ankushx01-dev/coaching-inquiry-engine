"""Consent service. Checks and revokes consent with audit trail."""

from __future__ import annotations

from uuid import UUID

from coaching_inquiry_engine.db.repositories.audits import AuditRepository
from coaching_inquiry_engine.db.repositories.consents import ConsentRepository
from coaching_inquiry_engine.domain.config import PROMPT_VERSION
from coaching_inquiry_engine.domain.consent import (
    can_send_outbound,
    is_consent_revocation,
)
from coaching_inquiry_engine.domain.models import ContactChannel


class ConsentService:
    def __init__(
        self,
        consent_repo: ConsentRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self._consent = consent_repo
        self._audit = audit_repo

    async def check_outbound_allowed(
        self, lead_id: UUID, channel: ContactChannel
    ) -> bool:
        granted = await self._consent.latest_consent_granted(lead_id, channel)
        return can_send_outbound(granted, channel.value)

    async def handle_revocation(
        self, lead_id: UUID, channel: ContactChannel, text: str
    ) -> str | None:
        """Revoke consent and return its response key for a matching phrase."""
        if not is_consent_revocation(text):
            return None
        await self._consent.revoke_consent(lead_id, channel)
        await self._audit.append_audit_event(
            lead_id=lead_id,
            event_type="consent_revoked",
            detail={"channel": channel.value, "trigger_text": "revocation_phrase"},
            prompt_version=PROMPT_VERSION,
        )
        return "consent_stopped"

    async def record_and_audit(
        self, lead_id: UUID, channel: ContactChannel, wording_version: str
    ) -> None:
        await self._consent.record_consent(lead_id, channel, wording_version)
        await self._audit.append_audit_event(
            lead_id=lead_id,
            event_type="consent_granted",
            detail={"channel": channel.value, "wording_version": wording_version},
            prompt_version=PROMPT_VERSION,
        )
