"""Lead qualification value objects. Pure Pydantic models, no framework imports."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

_PHONE_SEPARATORS = re.compile(r"[\s-]+")
_INDIAN_MOBILE = re.compile(r"^(?:\+91|0)?([6-9]\d{9})$")
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_ALLOWED_NAME_MARKS = {"Mn", "Mc"}
_ALLOWED_NAME_PUNCTUATION = frozenset(" .'-")


class Stage(StrEnum):
    first_attempt = "first_attempt"
    reattempt = "reattempt"
    working_professional = "working_professional"


class Target(StrEnum):
    prelims = "prelims"
    mains = "mains"
    full_course = "full_course"
    test_series = "test_series"


class Timeline(StrEnum):
    within_1_month = "within_1_month"
    within_3_months = "within_3_months"
    later = "later"


class ContactChannel(StrEnum):
    chat = "chat"
    whatsapp = "whatsapp"
    call = "call"
    email = "email"


class MessageDirection(StrEnum):
    inbound = "inbound"
    outbound = "outbound"


class OutboxStatus(StrEnum):
    pending = "pending"
    processing = "processing"
    sent = "sent"
    dead = "dead"


class BookingStatus(StrEnum):
    confirmed = "confirmed"
    cancelled = "cancelled"


class LeadStatus(StrEnum):
    qualified = "qualified"
    nurture = "nurture"
    out_of_scope = "out_of_scope"
    escalated = "escalated"
    minor_linked = "minor_linked"
    booked = "booked"
    lost = "lost"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def normalize_person_name(value: str) -> str:
    """Trim and validate a person name. Shared by Contact and FieldUpdates."""
    stripped = value.strip()
    if not 1 <= len(stripped) <= 60:
        raise ValueError("name must be between 1 and 60 characters")
    if not all(_is_allowed_name_char(char) for char in stripped):
        raise ValueError(
            "name may contain letters, spaces, dots, apostrophes, and hyphens only"
        )
    return stripped


class Contact(_StrictModel):
    name: str
    channel: ContactChannel
    value: str

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return normalize_person_name(value)

    @model_validator(mode="after")
    def validate_channel_value(self) -> Self:
        if self.channel in {ContactChannel.whatsapp, ContactChannel.call}:
            self.value = _normalize_indian_mobile(self.value)
        elif self.channel is ContactChannel.email:
            if _EMAIL.fullmatch(self.value) is None:
                raise ValueError("invalid email address")
        return self


class LeadProfile(_StrictModel):
    stage: Stage | None = None
    target: Target | None = None
    timeline: Timeline | None = None
    contact: Contact | None = None


class QualifyFlags(_StrictModel):
    is_minor: bool = False
    distress_detected: bool = False
    fee_dispute: bool = False
    complaint: bool = False
    scam_signal: bool = False
    self_harm: bool = False
    human_request: bool = False
    injection_attempt: bool = False


class Lead(_StrictModel):
    """Persisted lead identity and qualification snapshot. Contact is not included."""

    id: UUID
    channel: ContactChannel
    external_user_id: str
    status: LeadStatus
    stage: Stage | None = None
    target: Target | None = None
    timeline: Timeline | None = None
    name: str | None = None
    created_at: datetime
    updated_at: datetime


def _is_allowed_name_char(char: str) -> bool:
    if char.isalpha() or char in _ALLOWED_NAME_PUNCTUATION:
        return True
    return unicodedata.category(char) in _ALLOWED_NAME_MARKS


def _normalize_indian_mobile(raw: str) -> str:
    compact = _PHONE_SEPARATORS.sub("", raw)
    match = _INDIAN_MOBILE.fullmatch(compact)
    if match is None:
        raise ValueError("invalid Indian mobile number")
    return f"+91{match.group(1)}"
