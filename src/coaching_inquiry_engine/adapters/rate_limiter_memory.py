"""Thread-safe in-memory sliding-window limiter for the single-process API."""

from __future__ import annotations

from collections import deque
from threading import Lock
from time import monotonic


class InMemoryRateLimiter:
    def __init__(
        self,
        *,
        per_session_per_minute: int,
        per_ip_per_minute: int,
        window_seconds: float = 60,
    ) -> None:
        self._session_limit = per_session_per_minute
        self._ip_limit = per_ip_per_minute
        self._window = window_seconds
        self._sessions: dict[str, deque[float]] = {}
        self._ips: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, session_id: str, ip_address: str) -> bool:
        now = monotonic()
        with self._lock:
            session_times = self._active_times(self._sessions, session_id, now)
            ip_times = self._active_times(self._ips, ip_address, now)
            if (
                len(session_times) >= self._session_limit
                or len(ip_times) >= self._ip_limit
            ):
                return False
            session_times.append(now)
            ip_times.append(now)
            return True

    def _active_times(
        self,
        buckets: dict[str, deque[float]],
        key: str,
        now: float,
    ) -> deque[float]:
        times = buckets.setdefault(key, deque())
        while times and now - times[0] >= self._window:
            times.popleft()
        return times
