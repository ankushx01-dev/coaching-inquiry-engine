"""Rate-limit port for chat ingress."""

from __future__ import annotations

from typing import Protocol


class RateLimiterPort(Protocol):
    def allow(self, session_id: str, ip_address: str) -> bool: ...
