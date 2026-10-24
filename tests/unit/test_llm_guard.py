"""decide_safely retries vendor and validation failures, then gives up."""

from __future__ import annotations

import json

import httpx
import pytest

from coaching_inquiry_engine.adapters.llm_fake import FakeLlmAdapter
from coaching_inquiry_engine.domain import AgentDecision, NextAction
from coaching_inquiry_engine.ports.llm import DecisionContext, SanitizedMessage
from coaching_inquiry_engine.services.llm_guard import LLMUnavailable, decide_safely

_DECISION = AgentDecision(
    next_action=NextAction.ask_field,
    reply_text="Which stage of preparation are you in?",
    prompt_version="upsc_v0.2",
)
_CONTEXT = DecisionContext(
    messages=[SanitizedMessage(role="user", text="I want to enrol")],
    allowed_next_actions=[NextAction.ask_field],
)


async def test_fails_twice_then_succeeds() -> None:
    port = FakeLlmAdapter(
        [
            httpx.ConnectError("down"),
            httpx.ConnectError("down"),
            _DECISION,
        ]
    )
    decision = await decide_safely(port, _CONTEXT, max_attempts=3)
    assert decision == _DECISION
    assert port.calls == 3


async def test_fails_three_times_raises_unavailable() -> None:
    port = FakeLlmAdapter(
        [
            httpx.ConnectError("down"),
            httpx.ConnectError("down"),
            httpx.ConnectError("down"),
        ]
    )
    with pytest.raises(LLMUnavailable):
        await decide_safely(port, _CONTEXT, max_attempts=3)
    assert port.calls == 3


async def test_timeout_is_retried() -> None:
    port = FakeLlmAdapter(
        [
            httpx.TimeoutException("slow"),
            _DECISION,
        ]
    )
    decision = await decide_safely(port, _CONTEXT, max_attempts=3)
    assert decision == _DECISION
    assert port.calls == 2


async def test_invalid_json_is_retried() -> None:
    port = FakeLlmAdapter(
        [
            "{not json",
            _DECISION,
        ]
    )
    decision = await decide_safely(port, _CONTEXT, max_attempts=3)
    assert decision == _DECISION
    assert port.calls == 2


async def test_attempt_count_is_exactly_three() -> None:
    port = FakeLlmAdapter(
        [
            json.dumps({"next_action": "ask_field"}),
            httpx.TimeoutException("slow"),
            _DECISION,
        ]
    )
    decision = await decide_safely(port, _CONTEXT, max_attempts=3)
    assert decision == _DECISION
    assert port.calls == 3


async def test_personal_data_request_is_retried() -> None:
    unsafe = _DECISION.model_copy(
        update={"reply_text": "Can you tell me your date of birth?"}
    )
    port = FakeLlmAdapter([unsafe, _DECISION])

    decision = await decide_safely(port, _CONTEXT, max_attempts=2)

    assert decision == _DECISION
    assert port.calls == 2
