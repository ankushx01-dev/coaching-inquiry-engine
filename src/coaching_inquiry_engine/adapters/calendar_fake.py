"""In-memory CalendarPort for tests. Busy windows are injected by the caller."""

from __future__ import annotations

from datetime import UTC, datetime


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("calendar datetimes must be timezone-aware UTC")
    return value.astimezone(UTC)


class FakeCalendar:
    """Test double: busy intervals are explicit, create_event is idempotent."""

    def __init__(self) -> None:
        self._busy: list[tuple[datetime, datetime]] = []
        self._events: dict[str, str] = {}
        self.create_event_calls = 0
        self.busy_interval_calls = 0

    def add_busy(self, start: datetime, end: datetime) -> None:
        self._busy.append((_require_utc(start), _require_utc(end)))

    def busy_intervals(
        self, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]:
        self.busy_interval_calls += 1
        window_start = _require_utc(start)
        window_end = _require_utc(end)
        return [
            (busy_start, busy_end)
            for busy_start, busy_end in self._busy
            if busy_start < window_end and busy_end > window_start
        ]

    def create_event(
        self,
        idempotency_key: str,
        start: datetime,
        duration_min: int,
        title: str,
    ) -> str:
        _ = title
        _require_utc(start)
        if duration_min <= 0:
            raise ValueError("duration_min must be positive")
        self.create_event_calls += 1
        existing = self._events.get(idempotency_key)
        if existing is not None:
            return existing
        event_id = f"evt-{len(self._events) + 1}"
        self._events[idempotency_key] = event_id
        return event_id

    @property
    def event_ids(self) -> list[str]:
        return list(self._events.values())
