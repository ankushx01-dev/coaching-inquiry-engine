"""Shared test fixtures. Encryption keys are set before the app is imported."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet

os.environ.setdefault("CIE_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
os.environ.setdefault("CIE_CONTACT_HASH_KEY", "unit-test-contact-hash-key")
os.environ.setdefault("APP_ENV", "test")
