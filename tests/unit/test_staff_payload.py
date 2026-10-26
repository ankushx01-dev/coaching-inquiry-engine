"""PII masking and message-window tests for staff payloads."""

from __future__ import annotations

import re
from uuid import UUID

from coaching_inquiry_engine.domain.models import (
    ContactChannel,
    LeadStatus,
    QualifyFlags,
)
from coaching_inquiry_engine.services.escalation_service import build_staff_payload


def test_staff_payload_masks_contacts_and_keeps_only_last_five_messages() -> None:
    phone_contact = "+919876543210"
    raw_phone = "9876543210"
    email_contact = "asha.sharma@example.com"
    messages = [
        "message 0 should be dropped",
        "message 1",
        "message 2",
        "message 3",
        "message 4",
        f"message 5 contact {phone_contact} and {email_contact}",
    ]

    payload = build_staff_payload(
        lead_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        status=LeadStatus.escalated,
        reason="safety_review",
        messages=messages,
        flags=QualifyFlags(distress_detected=True),
    )
    serialized = payload.model_dump_json()

    assert len(payload.recent_messages) == 5
    assert payload.recent_messages[0] == "message 1"
    assert payload.recent_messages[-1].startswith("message 5 contact")
    assert "message 0 should be dropped" not in serialized
    assert re.search(r"(?<!\d)\d{10,}(?!\d)", serialized) is None
    assert (
        re.search(
            r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
            serialized,
        )
        is None
    )
    assert phone_contact not in serialized
    assert raw_phone not in serialized
    assert email_contact not in serialized
    assert ContactChannel.whatsapp.value not in serialized


def test_counselling_alert_serializes_only_approved_masked_fields() -> None:
    phone = "+919876543210"
    email = "asha.sharma@example.com"
    payload = build_staff_payload(
        lead_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        status=LeadStatus.nurture,
        reason="counselling_request",
        messages=[f"{phone} {email}"],
        flags=QualifyFlags(),
        counselling_request=True,
        first_name="Asha",
        exam="UPSC Civil Services Examination",
        eligibility_status="eligible",
    )
    data = payload.model_dump(mode="json", exclude_none=True)
    serialized = payload.model_dump_json(exclude_none=True)

    assert set(data) == {"lead_id", "first_name", "exam", "eligibility_status"}
    assert data["first_name"] == "Asha"
    assert "Asha Sharma" not in serialized
    assert phone not in serialized and email not in serialized
    assert re.search(r"(?<!\d)\d{10,}(?!\d)", serialized) is None
