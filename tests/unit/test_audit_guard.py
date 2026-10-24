"""Unit tests for append-only audit contact guards."""

from __future__ import annotations

import pytest

from coaching_inquiry_engine.db.audit import (
    FORBIDDEN_AUDIT_KEYS,
    ForbiddenAuditKeyError,
    assert_safe_audit_detail,
)
from coaching_inquiry_engine.db.repositories.audits import AuditRepository


@pytest.mark.parametrize("key", sorted(FORBIDDEN_AUDIT_KEYS))
def test_forbidden_detail_keys_raise(key: str) -> None:
    with pytest.raises(ForbiddenAuditKeyError, match=key):
        assert_safe_audit_detail({key: "secret"})


def test_nested_forbidden_detail_key_raises() -> None:
    with pytest.raises(ForbiddenAuditKeyError, match="email"):
        assert_safe_audit_detail({"meta": {"email": "hidden"}})


def test_allowed_detail_is_accepted() -> None:
    assert_safe_audit_detail(
        {"event": "status_changed", "from": "nurture", "to": "qualified"}
    )


def test_audit_repository_has_no_update_or_delete() -> None:
    public = {
        name
        for name in dir(AuditRepository)
        if not name.startswith("_") and callable(getattr(AuditRepository, name))
    }
    assert "append_audit_event" in public
    assert "update" not in public
    assert "delete" not in public
    assert "remove" not in public
