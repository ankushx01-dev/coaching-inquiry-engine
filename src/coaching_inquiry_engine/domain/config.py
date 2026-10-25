"""Domain configuration. Offered products and source hosts are data, not rules."""

from collections.abc import Mapping
from datetime import time
from types import MappingProxyType
from zoneinfo import ZoneInfo

from coaching_inquiry_engine.domain.models import Target

OFFERED_TARGETS: frozenset[Target] = frozenset(Target)

UPSC_OFFICIAL_HOST = "upsc.gov.in"
INSTITUTE_DOMAIN = "institute.example"
INSTITUTE_NAME = "Example Coaching Institute"
PROMPT_VERSION = "upsc_v0.2"
DOCUMENTED_PROMPT_PLACEHOLDERS: frozenset[str] = frozenset({"institute_name"})

FALLBACK_TEXTS: Mapping[str, str] = MappingProxyType(
    {
        "stale": (
            "[TO_APPROVE] Director-approved wording for a stale source is not on file."
        ),
        "missing": (
            "[TO_APPROVE] Director-approved wording for a missing source "
            "is not on file."
        ),
    }
)

BOOKING_TZ = ZoneInfo("Asia/Kolkata")
BOOKING_DURATION_MIN = 30
BOOKING_LEAD_MIN = 120
BOOKING_BUFFER_MIN = 15
BOOKING_DAYS = 7
BOOKING_OFFER_LIMIT = 3
BOOKING_OFFER_TTL_MIN = 30
BOOKING_STEP_MIN = 30
_OPEN = time(10, 0)
_CLOSE = time(18, 0)
# Monday=0 … Saturday=5. Sunday is omitted and treated as closed.
BUSINESS_HOURS: Mapping[int, tuple[time, time]] = MappingProxyType(
    {weekday: (_OPEN, _CLOSE) for weekday in range(6)}
)
