"""Use-case repositories. Each class is one aggregate."""

from coaching_inquiry_engine.db.repositories.audits import AuditRepository
from coaching_inquiry_engine.db.repositories.bookings import BookingRepository
from coaching_inquiry_engine.db.repositories.consents import ConsentRepository
from coaching_inquiry_engine.db.repositories.leads import LeadRepository
from coaching_inquiry_engine.db.repositories.messages import MessageRepository

__all__ = [
    "AuditRepository",
    "BookingRepository",
    "ConsentRepository",
    "LeadRepository",
    "MessageRepository",
]
