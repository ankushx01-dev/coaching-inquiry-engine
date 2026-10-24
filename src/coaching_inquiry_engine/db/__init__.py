"""Database engine, sessions, and ORM models."""

from coaching_inquiry_engine.db.audit import (
    FORBIDDEN_AUDIT_KEYS,
    ForbiddenAuditKeyError,
    assert_safe_audit_detail,
)
from coaching_inquiry_engine.db.base import Base
from coaching_inquiry_engine.db.encryption import (
    ContactCipher,
    MissingEncryptionKeyError,
    require_crypto_settings,
)
from coaching_inquiry_engine.db.repositories import (
    AuditRepository,
    ConsentRepository,
    LeadRepository,
    MessageRepository,
)
from coaching_inquiry_engine.db.session import create_engine, create_session_factory

__all__ = [
    "FORBIDDEN_AUDIT_KEYS",
    "AuditRepository",
    "Base",
    "ConsentRepository",
    "ContactCipher",
    "ForbiddenAuditKeyError",
    "LeadRepository",
    "MessageRepository",
    "MissingEncryptionKeyError",
    "assert_safe_audit_detail",
    "create_engine",
    "create_session_factory",
    "require_crypto_settings",
]
