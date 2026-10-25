"""Retry wrapper around the LLM port. Never returns a guessed decision."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx
import structlog
from pydantic import ValidationError

from coaching_inquiry_engine.config import get_settings
from coaching_inquiry_engine.domain.config import PROMPT_VERSION
from coaching_inquiry_engine.domain.decisions import AgentDecision
from coaching_inquiry_engine.domain.llm_checks import (
    DecisionRejectedError,
    check_decision,
)
from coaching_inquiry_engine.ports.llm import DecisionContext, LlmPort

logger = structlog.get_logger("llm_guard")

_RETRYABLE = (
    httpx.HTTPError,
    httpx.TimeoutException,
    ValidationError,
    DecisionRejectedError,
)


class LLMUnavailable(Exception):  # noqa: N818
    """The LLM port did not produce a valid decision after all attempts."""


async def decide_safely(
    port: LlmPort,
    context: DecisionContext,
    *,
    max_attempts: int | None = None,
    decision_validator: Callable[[AgentDecision], None] | None = None,
) -> AgentDecision:
    settings = get_settings()
    attempts = settings.llm_max_attempts if max_attempts is None else max_attempts
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        started = time.perf_counter()
        try:
            decision = await port.decide(context)
            check_decision(
                decision,
                offered_indices=frozenset(
                    option.index for option in context.slot_options
                ),
                allowed_snippets=(
                    *(option.label for option in context.slot_options),
                    *(entry.text for entry in context.knowledge_entries),
                ),
                required_citation_ids=(
                    entry.id for entry in context.knowledge_entries
                ),
            )
            if decision_validator is not None:
                decision_validator(decision)
        except _RETRYABLE as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            logger.warning(
                "llm_decide_failed",
                attempt=attempt,
                error_type=type(exc).__name__,
                latency_ms=round(latency_ms, 1),
                prompt_version=PROMPT_VERSION,
            )
            last_error = exc
            continue
        latency_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "llm_decide",
            attempt=attempt,
            error_type=None,
            latency_ms=round(latency_ms, 1),
            prompt_version=decision.prompt_version,
        )
        return decision
    raise LLMUnavailable("LLM did not return a valid decision") from last_error
