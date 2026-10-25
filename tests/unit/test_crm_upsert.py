"""CRM contact upserts are idempotent by stable lead UUID."""

from __future__ import annotations

from uuid import UUID

from coaching_inquiry_engine.adapters.crm_fake import FakeCrm


async def test_same_lead_reference_twice_creates_one_fake_contact() -> None:
    crm = FakeCrm()
    lead_ref = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    await crm.upsert_contact(lead_ref, {"source_event": "chat"})
    await crm.upsert_contact(lead_ref, {"source_event": "booking"})

    assert len(crm.contacts) == 1
    assert crm.contacts[lead_ref] == {"source_event": "booking"}
    assert len(crm.upsert_calls) == 2
