"""Counselling request values independent of HTTP and persistence details."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CounsellingRequestStatus(StrEnum):
    new = "new"
    contacted = "contacted"
    booked = "booked"
    closed = "closed"


class CounsellingRequestSummary(BaseModel):
    """Privacy-safe values used to create staff alerts and list rows."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    lead_id: UUID
    first_name: str | None
    exam: str | None
    eligibility_status: str | None
    status: CounsellingRequestStatus
