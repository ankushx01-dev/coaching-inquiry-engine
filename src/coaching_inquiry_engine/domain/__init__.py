"""Domain logic — pure Python, no framework imports."""

from coaching_inquiry_engine.domain.config import (
    DOCUMENTED_PROMPT_PLACEHOLDERS,
    FALLBACK_TEXTS,
    INSTITUTE_DOMAIN,
    INSTITUTE_NAME,
    OFFERED_TARGETS,
    PROMPT_VERSION,
    UPSC_OFFICIAL_HOST,
)
from coaching_inquiry_engine.domain.decisions import (
    AgentDecision,
    EscalationReason,
    FieldUpdates,
    NextAction,
    SlotOption,
)
from coaching_inquiry_engine.domain.llm_checks import (
    DecisionRejectedError,
    check_decision,
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
    "DOCUMENTED_PROMPT_PLACEHOLDERS",
    "FALLBACK_TEXTS",
    "INSTITUTE_DOMAIN",
    "INSTITUTE_NAME",
    "OFFERED_TARGETS",
    "PROMPT_VERSION",
    "UPSC_OFFICIAL_HOST",
    "AgentDecision",
    "DecisionRejectedError",
    "EscalationReason",
    "FieldUpdates",
    "NextAction",
    "SlotOption",
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
    "check_decision",
    "get_source",
    "load_sources",
    "qualify",
]
