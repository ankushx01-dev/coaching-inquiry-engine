"""Domain configuration. Offered products and source hosts are data, not rules."""

from collections.abc import Mapping
from types import MappingProxyType

from coaching_inquiry_engine.domain.models import Target

OFFERED_TARGETS: frozenset[Target] = frozenset(Target)

UPSC_OFFICIAL_HOST = "upsc.gov.in"
INSTITUTE_DOMAIN = "institute.example"

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
