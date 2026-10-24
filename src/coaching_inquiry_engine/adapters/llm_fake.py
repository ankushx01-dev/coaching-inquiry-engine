"""Scripted LLM adapter for tests. No network."""

from __future__ import annotations

from collections import deque

from coaching_inquiry_engine.domain.decisions import AgentDecision
from coaching_inquiry_engine.ports.llm import DecisionContext

type ScriptItem = AgentDecision | BaseException | str


class FakeLlmAdapter:
    """Returns queued decisions. Raises or parses JSON when scripted to do so."""

    def __init__(self, script: list[ScriptItem] | None = None) -> None:
        self._queue: deque[ScriptItem] = deque(script or [])
        self.calls = 0

    def enqueue(self, item: ScriptItem) -> None:
        self._queue.append(item)

    async def decide(self, context: DecisionContext) -> AgentDecision:
        _ = context
        self.calls += 1
        if not self._queue:
            raise RuntimeError("FakeLlmAdapter queue is empty")
        item = self._queue.popleft()
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, str):
            return AgentDecision.model_validate_json(item)
        return item
