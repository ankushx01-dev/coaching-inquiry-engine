"""Consent management logic. Pure domain functions, no I/O."""

from __future__ import annotations


def can_send_outbound(granted: bool, channel: str) -> bool:
    """Return True only when consent is explicitly granted for the channel."""
    return granted


_STOP_PHRASES: frozenset[str] = frozenset({
    "stop",
    "unsubscribe",
    "band karo",
})


def is_consent_revocation(text: str) -> bool:
    """Check if the text is a consent revocation phrase."""
    normalized = text.strip().lower()
    return normalized in _STOP_PHRASES
