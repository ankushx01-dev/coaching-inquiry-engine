"""LLM port. DecisionContext is the only payload the model is allowed to see."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from coaching_inquiry_engine.domain.decisions import (
    AgentDecision,
    FieldUpdates,
    NextAction,
    SlotOption,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SanitizedMessage(_StrictModel):
    role: str = Field(pattern="^(user|assistant)$")
    text: str = Field(min_length=1, max_length=2000)


class KnowledgeContextEntry(_StrictModel):
    id: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=2000)
    status: str = Field(pattern="^(VERIFIED|STALE)$")
    source: str = Field(min_length=1, max_length=500)


class DecisionContext(_StrictModel):
    messages: list[SanitizedMessage] = Field(max_length=10)
    profile: FieldUpdates = Field(default_factory=FieldUpdates)
    allowed_next_actions: list[NextAction]
    slot_options: list[SlotOption] = Field(default_factory=list)
    knowledge_entries: list[KnowledgeContextEntry] = Field(
        default_factory=list, max_length=3
    )


class LlmPort(Protocol):
    async def decide(self, context: DecisionContext) -> AgentDecision: ...
