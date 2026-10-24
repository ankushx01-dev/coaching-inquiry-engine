"""Domain logic — pure Python, no framework imports."""

from coaching_inquiry_engine.domain.config import (
    FALLBACK_TEXTS,
    INSTITUTE_DOMAIN,
    OFFERED_TARGETS,
    UPSC_OFFICIAL_HOST,
)
from coaching_inquiry_engine.domain.models import (
    BookingStatus,
    Contact,
    ContactChannel,
    Lead,
    LeadProfile,
    LeadStatus,
    MessageDirection,
    OutboxStatus,
    QualifyFlags,
    Stage,
    Target,
    Timeline,
)
from coaching_inquiry_engine.domain.qualify import qualify
from coaching_inquiry_engine.domain.sources import (
    Found,
    Missing,
    SourceEntry,
    SourceLoadError,
    Stale,
    get_source,
    load_sources,
)

__all__ = [
    "FALLBACK_TEXTS",
    "INSTITUTE_DOMAIN",
    "OFFERED_TARGETS",
    "UPSC_OFFICIAL_HOST",
    "BookingStatus",
    "Contact",
    "ContactChannel",
    "Found",
    "Lead",
    "LeadProfile",
    "LeadStatus",
    "MessageDirection",
    "OutboxStatus",
    "Missing",
    "QualifyFlags",
    "SourceEntry",
    "SourceLoadError",
    "Stage",
    "Stale",
    "Target",
    "Timeline",
    "get_source",
    "load_sources",
    "qualify",
]
