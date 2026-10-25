"""Unit tests for consent decisions and revocation handling."""

from __future__ import annotations

from uuid import UUID

import pytest

from coaching_inquiry_engine.domain.consent import can_send_outbound
from coaching_inquiry_engine.domain.models import ContactChannel
from coaching_inquiry_engine.services.consent_service import ConsentService


@pytest.mark.parametrize(
    ("state", "granted", "expected"),
    [
        ("no consent record", False, False),
        ("granted and unrevoked", True, True),
        ("revoked", False, False),
    ],
)
def test_can_send_outbound_requires_current_consent(
    state: str, granted: bool, expected: bool
) -> None:
    _ = state
    assert can_send_outbound(granted, ContactChannel.whatsapp.value) is expected


class _ConsentRepository:
    def __init__(self) -> None:
        self.revoked_channels: list[ContactChannel] = []

    async def revoke_consent(self, lead_id: UUID, channel: ContactChannel) -> None:
        _ = lead_id
        self.revoked_channels.append(channel)


class _AuditRepository:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def append_audit_event(
        self,
        *,
        lead_id: UUID,
        event_type: str,
        detail: dict[str, object],
        prompt_version: str,
    ) -> None:
        self.events.append(
            {
                "lead_id": lead_id,
                "event_type": event_type,
                "detail": detail,
                "prompt_version": prompt_version,
            }
        )


@pytest.mark.parametrize("text", ["STOP", "UNSUBSCRIBE", "band karo"])
async def test_revocation_phrases_revoke_and_return_stopped_key(text: str) -> None:
    consent_repo = _ConsentRepository()
    audit_repo = _AuditRepository()
    service = ConsentService(consent_repo, audit_repo)  # type: ignore[arg-type]
    lead_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    result = await service.handle_revocation(
        lead_id, ContactChannel.whatsapp, text
    )

    assert consent_repo.revoked_channels == [ContactChannel.whatsapp]
    assert len(audit_repo.events) == 1
    assert result == "consent_stopped"
