"""Unit tests for deterministic lead qualification."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from coaching_inquiry_engine.domain import (
    OFFERED_TARGETS,
    Contact,
    ContactChannel,
    LeadProfile,
    LeadStatus,
    QualifyFlags,
    Stage,
    Target,
    Timeline,
    qualify,
)

_COMPLETE_CONTACT = Contact(
    name="Ada Lovelace",
    channel=ContactChannel.whatsapp,
    value="9876543210",
)


def _complete_profile(
    *,
    stage: Stage = Stage.first_attempt,
    target: Target = Target.prelims,
    timeline: Timeline = Timeline.within_1_month,
    contact: Contact | None = _COMPLETE_CONTACT,
) -> LeadProfile:
    return LeadProfile(stage=stage, target=target, timeline=timeline, contact=contact)


@pytest.mark.parametrize(
    ("profile", "flags", "offered", "expected"),
    [
        (
            _complete_profile(),
            QualifyFlags(is_minor=True),
            OFFERED_TARGETS,
            LeadStatus.minor_linked,
        ),
        (
            _complete_profile(),
            QualifyFlags(distress_detected=True),
            OFFERED_TARGETS,
            LeadStatus.escalated,
        ),
        (
            _complete_profile(target=Target.mains),
            QualifyFlags(),
            frozenset({Target.prelims}),
            LeadStatus.out_of_scope,
        ),
        (
            _complete_profile(timeline=Timeline.later),
            QualifyFlags(),
            OFFERED_TARGETS,
            LeadStatus.nurture,
        ),
        (
            _complete_profile(),
            QualifyFlags(),
            OFFERED_TARGETS,
            LeadStatus.qualified,
        ),
        (
            LeadProfile(stage=Stage.reattempt),
            QualifyFlags(),
            OFFERED_TARGETS,
            LeadStatus.nurture,
        ),
    ],
    ids=[
        "minor_linked",
        "escalated",
        "out_of_scope",
        "nurture_later",
        "qualified",
        "nurture_incomplete",
    ],
)
def test_qualify_one_outcome_per_lead_status(
    profile: LeadProfile,
    flags: QualifyFlags,
    offered: frozenset[Target],
    expected: LeadStatus,
) -> None:
    assert qualify(profile, flags, offered) == expected


@pytest.mark.parametrize(
    ("flags", "profile", "offered", "expected"),
    [
        (
            QualifyFlags(is_minor=True, distress_detected=True),
            _complete_profile(),
            OFFERED_TARGETS,
            LeadStatus.minor_linked,
        ),
        (
            QualifyFlags(
                is_minor=True,
                scam_signal=True,
                complaint=True,
                fee_dispute=True,
            ),
            _complete_profile(),
            OFFERED_TARGETS,
            LeadStatus.minor_linked,
        ),
        (
            QualifyFlags(is_minor=True),
            _complete_profile(target=Target.test_series, timeline=Timeline.later),
            frozenset({Target.prelims}),
            LeadStatus.minor_linked,
        ),
        (
            QualifyFlags(distress_detected=True),
            _complete_profile(),
            OFFERED_TARGETS,
            LeadStatus.escalated,
        ),
        (
            QualifyFlags(distress_detected=True, scam_signal=True),
            _complete_profile(timeline=Timeline.later),
            frozenset({Target.prelims}),
            LeadStatus.escalated,
        ),
        (
            QualifyFlags(scam_signal=True),
            _complete_profile(),
            OFFERED_TARGETS,
            LeadStatus.escalated,
        ),
        (
            QualifyFlags(complaint=True),
            _complete_profile(),
            OFFERED_TARGETS,
            LeadStatus.escalated,
        ),
        (
            QualifyFlags(fee_dispute=True),
            _complete_profile(),
            OFFERED_TARGETS,
            LeadStatus.escalated,
        ),
        (
            QualifyFlags(scam_signal=True, complaint=True, fee_dispute=True),
            _complete_profile(timeline=Timeline.later),
            frozenset({Target.full_course}),
            LeadStatus.escalated,
        ),
        (
            QualifyFlags(),
            _complete_profile(target=Target.full_course, timeline=Timeline.later),
            frozenset({Target.prelims, Target.mains}),
            LeadStatus.out_of_scope,
        ),
        (
            QualifyFlags(),
            _complete_profile(timeline=Timeline.later),
            OFFERED_TARGETS,
            LeadStatus.nurture,
        ),
    ],
    ids=[
        "minor_beats_distress",
        "minor_beats_escalation_flags",
        "minor_beats_scope_and_later",
        "distress_beats_qualified",
        "distress_beats_scam_scope_later",
        "scam_beats_qualified",
        "complaint_beats_qualified",
        "fee_dispute_beats_qualified",
        "escalation_flags_beat_scope_and_later",
        "out_of_scope_beats_later_and_qualified",
        "later_beats_qualified",
    ],
)
def test_qualify_priority_conflicts(
    flags: QualifyFlags,
    profile: LeadProfile,
    offered: frozenset[Target],
    expected: LeadStatus,
) -> None:
    assert qualify(profile, flags, offered) == expected


@pytest.mark.parametrize(
    "flag_name",
    ["scam_signal", "complaint", "fee_dispute"],
)
def test_escalation_flags_without_distress(flag_name: str) -> None:
    flags = QualifyFlags(**{flag_name: True})
    assert qualify(_complete_profile(), flags, OFFERED_TARGETS) is LeadStatus.escalated


def test_missing_contact_is_nurture_not_qualified() -> None:
    profile = _complete_profile(contact=None)
    assert qualify(profile, QualifyFlags(), OFFERED_TARGETS) is LeadStatus.nurture


def test_missing_stage_is_nurture_not_qualified() -> None:
    profile = LeadProfile(
        target=Target.prelims,
        timeline=Timeline.within_3_months,
        contact=_COMPLETE_CONTACT,
    )
    assert qualify(profile, QualifyFlags(), OFFERED_TARGETS) is LeadStatus.nurture


def test_missing_target_skips_out_of_scope_and_nurtures() -> None:
    profile = LeadProfile(
        stage=Stage.working_professional,
        timeline=Timeline.within_1_month,
        contact=_COMPLETE_CONTACT,
    )
    assert qualify(profile, QualifyFlags(), frozenset()) is LeadStatus.nurture


def test_offered_targets_come_from_config_not_rule_hardcoding() -> None:
    assert OFFERED_TARGETS == frozenset(Target)
    narrowed = frozenset({Target.test_series})
    assert (
        qualify(_complete_profile(target=Target.prelims), QualifyFlags(), narrowed)
        is LeadStatus.out_of_scope
    )


@pytest.mark.parametrize(
    "raw",
    ["12345", "5123456789", "98765abc10"],
)
def test_invalid_phone_numbers_are_rejected(raw: str) -> None:
    with pytest.raises(ValidationError):
        Contact(name="Priya", channel=ContactChannel.call, value=raw)


@pytest.mark.parametrize(
    "raw",
    ["098765 43210", "+91 98765-43210"],
)
def test_phone_normalization(raw: str) -> None:
    contact = Contact(name="Priya", channel=ContactChannel.whatsapp, value=raw)
    assert contact.value == "+919876543210"


@pytest.mark.parametrize(
    "raw",
    ["9876543210", "09876543210", "+919876543210"],
)
def test_phone_accepted_shapes(raw: str) -> None:
    contact = Contact(name="Priya", channel=ContactChannel.call, value=raw)
    assert contact.value == "+919876543210"


@pytest.mark.parametrize(
    "name",
    ["John123", "Hi 😀", "John@Doe"],
)
def test_invalid_names_are_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        Contact(name=name, channel=ContactChannel.email, value="ada@example.com")


@pytest.mark.parametrize(
    "name",
    ["A. P. J. Abdul Kalam", "O'Brien", "Mary-Jane", "अंकुश राना", "प्रिया", "  Ada  "],
)
def test_valid_names_are_accepted(name: str) -> None:
    contact = Contact(name=name, channel=ContactChannel.email, value="ada@example.com")
    assert contact.name == name.strip()
    assert 1 <= len(contact.name) <= 60


def test_name_surrounding_whitespace_is_trimmed() -> None:
    contact = Contact(
        name="  Ada Lovelace  ",
        channel=ContactChannel.email,
        value="ada@example.com",
    )
    assert contact.name == "Ada Lovelace"


def test_blank_name_after_trim_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Contact(name="   ", channel=ContactChannel.email, value="ada@example.com")


def test_invalid_email_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Contact(name="Ada", channel=ContactChannel.email, value="not-an-email")


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            Contact,
            {
                "name": "Ada",
                "channel": "email",
                "value": "ada@example.com",
                "nickname": "A",
            },
        ),
        (
            LeadProfile,
            {"stage": "first_attempt", "unknown": True},
        ),
        (
            QualifyFlags,
            {"is_minor": False, "unexpected": True},
        ),
    ],
)
def test_extra_fields_are_rejected(
    model: type[object],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)  # type: ignore[attr-defined]


def test_lead_status_members() -> None:
    assert set(LeadStatus) == {
        LeadStatus.qualified,
        LeadStatus.nurture,
        LeadStatus.out_of_scope,
        LeadStatus.escalated,
        LeadStatus.minor_linked,
        LeadStatus.booked,
        LeadStatus.lost,
    }
