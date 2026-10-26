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
    status: str | None = None
    reason: str | None = None
    recent_messages: list[str] | None = None
    fired_flags: dict[str, bool] | None = None
    prompt_version: str | None = None
    first_name: str | None = None
    exam: str | None = None
    eligibility_status: str | None = None


# Staff alert delivery uses the existing escalation payload schema.
StaffAlertPayload = StaffNotificationPayload


def build_staff_payload(
    *,
    lead_id: UUID,
    status: LeadStatus,
    reason: str,
    messages: list[str],
    flags: QualifyFlags,
    counselling_request: bool = False,
    first_name: str | None = None,
    exam: str | None = None,
    eligibility_status: str | None = None,
) -> StaffNotificationPayload:
    """Build a staff notification payload with masked PII.

    Only the last 5 messages are included. All contact values and
    phone numbers are masked.
    """
    if counselling_request:
        return StaffNotificationPayload(
            lead_id=str(lead_id),
            first_name=first_name,
            exam=exam,
            eligibility_status=eligibility_status,
        )

    last_five = messages[-5:]
    masked = [mask_contact_text(msg) for msg in last_five]

    fired: dict[str, bool] = {
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
