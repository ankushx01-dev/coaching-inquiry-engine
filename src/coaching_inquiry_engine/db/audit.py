"""Append-only audit helpers. Rejects contact-shaped detail keys."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

FORBIDDEN_AUDIT_KEYS = frozenset({"phone", "email", "contact", "contact_value", "name"})


class ForbiddenAuditKeyError(ValueError):
    """Raised when an audit payload would store a contact-shaped field."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(
            f"Audit event detail must not include the key '{key}'. "
            "Phone numbers, emails, contact values, and names are not stored "
            "in audit events."
        )


def assert_safe_audit_detail(detail: object) -> None:
    """Reject mappings that use forbidden contact keys at any nesting level."""
    if isinstance(detail, Mapping):
        for key, value in detail.items():
            name = key if isinstance(key, str) else str(key)
            if name in FORBIDDEN_AUDIT_KEYS:
                raise ForbiddenAuditKeyError(name)
            assert_safe_audit_detail(value)
        return
    if isinstance(detail, Sequence) and not isinstance(detail, (str, bytes)):
        for item in detail:
            assert_safe_audit_detail(item)
