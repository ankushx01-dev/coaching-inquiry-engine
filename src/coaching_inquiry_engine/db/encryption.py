"""Symmetric contact encryption and HMAC lookup hashes. No business rules."""

from __future__ import annotations

import hmac
from hashlib import sha256

from cryptography.fernet import Fernet

from coaching_inquiry_engine.config import Settings


class MissingEncryptionKeyError(RuntimeError):
    """Raised when the process would handle contact data without a key."""


def require_crypto_settings(settings: Settings) -> None:
    """Refuse to start if contact encryption cannot be performed."""
    if not settings.cie_encryption_key:
        raise MissingEncryptionKeyError(
            "CIE_ENCRYPTION_KEY is required; refusing to start without contact encryption."
        )
    if not settings.cie_contact_hash_key:
        raise MissingEncryptionKeyError(
            "CIE_CONTACT_HASH_KEY is required; refusing to start without a contact hash key."
        )


class ContactCipher:
    """Fernet encryption plus HMAC-SHA256 hashes of normalized contact values."""

    def __init__(self, encryption_key: str, hash_key: str) -> None:
        self._fernet = Fernet(encryption_key.encode("utf-8"))
        self._hash_key = hash_key.encode("utf-8")

    @classmethod
    def from_settings(cls, settings: Settings) -> ContactCipher:
        require_crypto_settings(settings)
        encryption_key = settings.cie_encryption_key
        hash_key = settings.cie_contact_hash_key
        if encryption_key is None or hash_key is None:
            raise MissingEncryptionKeyError(
                "CIE_ENCRYPTION_KEY is required; refusing to start without contact encryption."
            )
        return cls(encryption_key=encryption_key, hash_key=hash_key)

    def encrypt(self, normalized_value: str) -> bytes:
        return self._fernet.encrypt(normalized_value.encode("utf-8"))

    def decrypt(self, token: bytes) -> str:
        return self._fernet.decrypt(token).decode("utf-8")

    def hash_contact(self, normalized_value: str) -> str:
        digest = hmac.new(
            self._hash_key,
            normalized_value.encode("utf-8"),
            sha256,
        )
        return digest.hexdigest()
