"""LLM decision value objects. No HTTP or vendor imports."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from coaching_inquiry_engine.domain.models import (
    Stage,
    Target,
    Timeline,
    normalize_person_name,
)


class NextAction(StrEnum):
    """Allowed LLM actions, aligned with the conversation engine."""

    ask_field = "ask_field"
    answer_question = "answer_question"
    offer_slots = "offer_slots"
    booking_choice = "booking_choice"
    escalate = "escalate"
    close = "close"
    redirect_off_topic = "redirect_off_topic"
    nurture = "nurture"


class EscalationReason(StrEnum):
    """Reasons that map onto NotifyStaff in the conversation engine."""

    unresolved = "unresolved"
    off_topic_limit = "off_topic_limit"
    escalated = "escalated"
    minor_linked = "minor_linked"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldUpdates(_StrictModel):
    """Partial LeadProfile: stage, target, timeline, and contact name only."""

    stage: Stage | None = None
    target: Target | None = None
    timeline: Timeline | None = None
    contact_name: str | None = None

    @field_validator("contact_name")
    @classmethod
    def validate_contact_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_person_name(value)


class SlotOption(_StrictModel):
    """Human-readable slot label. No raw datetimes."""

    index: int = Field(ge=0, le=2)
    label: str = Field(min_length=1, max_length=120)


class AgentDecision(_StrictModel):
    next_action: NextAction
    reply_text: str = Field(min_length=1, max_length=500)
    field_updates: FieldUpdates = Field(default_factory=FieldUpdates)
    booking_choice_index: int | None = Field(default=None, ge=0, le=2)
    escalation_reason: EscalationReason | None = None
    prompt_version: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def booking_index_only_for_booking_choice(self) -> Self:
        if (
            self.next_action is not NextAction.booking_choice
            and self.booking_choice_index is not None
        ):
            raise ValueError(
                "booking_choice_index must be None unless next_action is booking_choice"
            )
        return self
