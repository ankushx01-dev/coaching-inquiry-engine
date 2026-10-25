"""Exponential backoff and dead-letter boundary tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from coaching_inquiry_engine.services.job_retry import (
    is_dead_letter,
    retry_at,
    retry_delay,
)


def test_retry_backoff_is_exponential() -> None:
    assert [retry_delay(attempt) for attempt in range(1, 6)] == [
        timedelta(seconds=1),
        timedelta(seconds=2),
        timedelta(seconds=4),
        timedelta(seconds=8),
        timedelta(seconds=16),
    ]


def test_retry_at_adds_the_backoff_to_current_time() -> None:
    now = datetime(2026, 10, 25, tzinfo=UTC)
    assert retry_at(now, 3) == now + timedelta(seconds=4)


@pytest.mark.parametrize("attempt", [1, 2, 3, 4])
def test_jobs_are_not_dead_lettered_before_fifth_attempt(attempt: int) -> None:
    assert is_dead_letter(attempt, max_attempts=5) is False


def test_job_is_dead_lettered_on_fifth_attempt() -> None:
    assert is_dead_letter(5, max_attempts=5) is True
