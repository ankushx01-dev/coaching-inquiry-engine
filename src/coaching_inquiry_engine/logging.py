"""Application logging. Masks contact values before anything is emitted."""

from __future__ import annotations

import logging
import re
from typing import cast

import structlog
from structlog.typing import EventDict, WrappedLogger

_REDACTED = "[REDACTED]"
_INDIAN_PHONE = re.compile(r"(?<!\d)(?:\+91[\s-]*|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask_contact_text(value: str) -> str:
    """Replace Indian phone numbers and email addresses in a string."""
    masked = _EMAIL.sub(_REDACTED, value)
    return _INDIAN_PHONE.sub(_REDACTED, masked)


def _mask_value(value: object) -> object:
    if isinstance(value, str):
        return mask_contact_text(value)
    if isinstance(value, dict):
        return {key: _mask_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_mask_value(item) for item in value)
    return value


def mask_pii(
    _logger: WrappedLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
    """Structlog processor: mask phones and emails, including nested dicts."""
    masked = _mask_value(event_dict)
    return cast(EventDict, masked)


def configure_logging(log_level: str) -> None:
    """Configure structlog so every event passes through contact masking."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            mask_pii,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )
