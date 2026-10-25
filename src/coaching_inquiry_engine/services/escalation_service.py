"""Staff escalation payload builder."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from coaching_inquiry_engine.domain.config import PROMPT_VERSION
from coaching_inquiry_engine.domain.models import LeadStatus, QualifyFlags
from coaching_inquiry_engine.logging import mask_contact_text


class StaffNotificationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: str
    status: str
    reason: str
    recent_messages: list[str]
    fired_flags: dict[str, bool]
    prompt_version: str


# Staff alert delivery uses the existing escalation payload schema.
StaffAlertPayload = StaffNotificationPayload


def build_staff_payload(
    *,
    lead_id: UUID,
    status: LeadStatus,
    reason: str,
    messages: list[str],
    flags: QualifyFlags,
) -> StaffNotificationPayload:
    """Build a staff notification payload with masked PII.

    Only the last 5 messages are included. All contact values and
    phone numbers are masked.
    """
    last_five = messages[-5:]
    masked = [mask_contact_text(msg) for msg in last_five]

    fired = {
        field_name: value
        for field_name, value in flags.model_dump().items()
        if value is True
    }

    return StaffNotificationPayload(
        lead_id=str(lead_id),
        status=status.value,
        reason=reason,
        recent_messages=masked,
        fired_flags=fired,
        prompt_version=PROMPT_VERSION,
    )
