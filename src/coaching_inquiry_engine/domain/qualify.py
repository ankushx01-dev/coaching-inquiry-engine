"""Deterministic lead qualification. No I/O, no LLM."""

from coaching_inquiry_engine.domain.models import (
    LeadProfile,
    LeadStatus,
    QualifyFlags,
    Target,
    Timeline,
)


def qualify(
    profile: LeadProfile,
    flags: QualifyFlags,
    offered_targets: frozenset[Target],
) -> LeadStatus:
    """Return the first matching status, highest priority first."""
    if flags.is_minor:
        return LeadStatus.minor_linked
    if flags.distress_detected:
        return LeadStatus.escalated
    if flags.scam_signal or flags.complaint or flags.fee_dispute:
        return LeadStatus.escalated
    if profile.target is not None and profile.target not in offered_targets:
        return LeadStatus.out_of_scope
    if profile.timeline is Timeline.later:
        return LeadStatus.nurture
    if (
        profile.stage is not None
        and profile.target is not None
        and profile.timeline is not None
        and profile.contact is not None
    ):
        return LeadStatus.qualified
    return LeadStatus.nurture
