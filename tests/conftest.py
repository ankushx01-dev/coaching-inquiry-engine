"""Shared test fixtures. Encryption keys are set before the app is imported."""

from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("CIE_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
os.environ.setdefault("CIE_CONTACT_HASH_KEY", "unit-test-contact-hash-key")
os.environ.setdefault("APP_ENV", "test")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    markexpr = config.option.markexpr or ""
    selected = "live_llm" in markexpr and "not live_llm" not in markexpr
    if selected:
        return
    skip_live = pytest.mark.skip(reason="live_llm tests are skipped by default")
    for item in items:
        if "live_llm" in item.keywords:
            item.add_marker(skip_live)
