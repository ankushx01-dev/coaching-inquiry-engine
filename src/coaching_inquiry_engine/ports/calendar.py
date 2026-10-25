"""Calendar port. Datetimes at this boundary are timezone-aware UTC."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class CalendarPort(Protocol):
    def busy_intervals(
        self, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]:
        """Return busy windows overlapping [start, end), both UTC-aware."""

    def create_event(
        self,
        idempotency_key: str,
        start: datetime,
        duration_min: int,
        title: str,
    ) -> str:
        """Create a calendar event. The same key always returns the same event ID."""
