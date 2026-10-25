"""Settable UTC clock for deterministic tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class FakeClock:
    def __init__(self, current: datetime) -> None:
        self.set(current)

    def now(self) -> datetime:
        return self._current

    def set(self, current: datetime) -> None:
        if current.tzinfo is None or current.utcoffset() != UTC.utcoffset(current):
            raise ValueError("FakeClock values must be timezone-aware UTC datetimes")
        self._current = current.astimezone(UTC)

    def advance(self, delta: timedelta) -> datetime:
        if delta < timedelta(0):
            raise ValueError("FakeClock cannot move backwards")
        self._current += delta
        return self._current
