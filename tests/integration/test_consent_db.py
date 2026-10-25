"""Consent persistence and audit behavior against PostgreSQL."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from coaching_inquiry_engine.db.models import AuditEventRow
from coaching_inquiry_engine.db.repositories.audits import AuditRepository
from coaching_inquiry_engine.db.repositories.consents import ConsentRepository
from coaching_inquiry_engine.db.repositories.leads import LeadRepository
from coaching_inquiry_engine.domain.models import ContactChannel
from coaching_inquiry_engine.services.consent_service import ConsentService

pytestmark = pytest.mark.integration


async def test_grant_revoke_blocks_outbound_and_writes_one_revoke_audit(
    session: AsyncSession, cipher: object
) -> None:
    leads = LeadRepository(session, cipher)  # type: ignore[arg-type]
    lead = await leads.get_or_create_lead(ContactChannel.whatsapp, "consent-user")
    service = ConsentService(
        ConsentRepository(session),
        AuditRepository(session),
    )

    await service.record_and_audit(
        lead.id, ContactChannel.whatsapp, "wording-v1"
    )
    assert (
        await service.check_outbound_allowed(lead.id, ContactChannel.whatsapp) is True
    )

    revoked = await service.handle_revocation(
        lead.id, ContactChannel.whatsapp, "STOP"
    )
    allowed = await service.check_outbound_allowed(lead.id, ContactChannel.whatsapp)
    revoke_audits = await session.scalar(
        select(func.count())
        .select_from(AuditEventRow)
        .where(
            AuditEventRow.lead_id == lead.id,
            AuditEventRow.event_type == "consent_revoked",
        )
    )

    assert revoked == "consent_stopped"
    assert allowed is False
    assert revoke_audits == 1
