"""Unit tests for contact masking in log events."""

from __future__ import annotations

import json

from coaching_inquiry_engine.logging import mask_pii

_PHONE = "+919876543210"
_PHONE_LOCAL = "9876543210"
_PHONE_ZERO = "09876543210"
_EMAIL = "ada@example.com"
_NESTED_EMAIL = "priya@institute.example"


def test_phone_and_email_are_masked_including_nested_dicts() -> None:
    event = {
        "event": f"inbound from {_PHONE} {_EMAIL}",
        "payload": {
            "phone": _PHONE_LOCAL,
            "nested": {"email": _NESTED_EMAIL, "note": f"ring {_PHONE_ZERO}"},
        },
        "items": [f"write {_EMAIL}"],
    }

    masked = mask_pii(None, "info", event)
    blob = json.dumps(masked)

    assert _PHONE not in blob
    assert _PHONE_LOCAL not in blob
    assert _PHONE_ZERO not in blob
    assert _EMAIL not in blob
    assert _NESTED_EMAIL not in blob
    assert masked["payload"]["phone"] == "[REDACTED]"
    assert masked["payload"]["nested"]["email"] == "[REDACTED]"
    assert "[REDACTED]" in masked["event"]
