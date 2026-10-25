"""Retry timing and dead-letter policy for chat jobs."""

from __future__ import annotations

from datetime import datetime, timedelta


def retry_delay(attempt: int) -> timedelta:
    if attempt < 1:
        raise ValueError("attempt must be at least 1")
    return timedelta(seconds=2 ** (attempt - 1))


def is_dead_letter(attempt: int, max_attempts: int = 5) -> bool:
    if attempt < 1:
        raise ValueError("attempt must be at least 1")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    return attempt >= max_attempts


def retry_at(now: datetime, attempt: int) -> datetime:
    return now + retry_delay(attempt)
