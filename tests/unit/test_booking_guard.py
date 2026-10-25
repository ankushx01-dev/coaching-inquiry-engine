"""One test per booking rejection reason."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from coaching_inquiry_engine.agent.config import CONVERSATION_TEXTS
from coaching_inquiry_engine.domain.config import BOOKING_TZ, BUSINESS_HOURS
from coaching_inquiry_engine.domain.slots import (
    BookingRejected,
    Slot,
    SlotOffer,
    assert_offer_bookable,
    validate_booking,
)

_NOW = datetime(2026, 10, 26, 8, 0, tzinfo=BOOKING_TZ)
_LEAD = uuid4()


def _offer(**overrides: object) -> SlotOffer:
    payload: dict[str, object] = {
        "id": uuid4(),
        "lead_id": _LEAD,
        "option_index": 0,
        "start": datetime(2026, 10, 26, 10, 0, tzinfo=BOOKING_TZ),
        "duration_min": 30,
        "expires_at": _NOW + timedelta(minutes=30),
        "used": False,
    }
    payload.update(overrides)
    return SlotOffer.model_validate(payload)


def _slot(start: datetime | None = None) -> Slot:
    return Slot(
        start=start or datetime(2026, 10, 26, 10, 0, tzinfo=BOOKING_TZ),
        duration_min=30,
    )


def test_offer_not_found() -> None:
    with pytest.raises(BookingRejected) as caught:
        assert_offer_bookable(None, lead_id=_LEAD, now=_NOW)
    assert caught.value.reason == "offer_not_found"


def test_offer_wrong_lead() -> None:
    with pytest.raises(BookingRejected) as caught:
        assert_offer_bookable(_offer(), lead_id=uuid4(), now=_NOW)
    assert caught.value.reason == "offer_wrong_lead"


def test_offer_used() -> None:
    with pytest.raises(BookingRejected) as caught:
        assert_offer_bookable(_offer(used=True), lead_id=_LEAD, now=_NOW)
    assert caught.value.reason == "offer_used"


def test_offer_expired() -> None:
    with pytest.raises(BookingRejected) as caught:
        assert_offer_bookable(
            _offer(expires_at=_NOW - timedelta(seconds=1)),
            lead_id=_LEAD,
            now=_NOW,
        )
    assert caught.value.reason == "offer_expired"


def test_slot_taken() -> None:
    busy = (
        (
            datetime(2026, 10, 26, 10, 0, tzinfo=BOOKING_TZ),
            datetime(2026, 10, 26, 10, 30, tzinfo=BOOKING_TZ),
        ),
    )
    with pytest.raises(BookingRejected) as caught:
        validate_booking(
            _slot(),
            now=_NOW,
            tz=BOOKING_TZ,
            hours=BUSINESS_HOURS,
            busy=busy,
            lead_min=0,
            buffer_min=0,
        )
    assert caught.value.reason == "slot_taken"


def test_slot_invalid() -> None:
    sunday = datetime(2026, 10, 25, 11, 0, tzinfo=BOOKING_TZ)
    with pytest.raises(BookingRejected) as caught:
        validate_booking(
            _slot(sunday),
            now=datetime(2026, 10, 25, 8, 0, tzinfo=BOOKING_TZ),
            tz=BOOKING_TZ,
            hours=BUSINESS_HOURS,
            busy=(),
            lead_min=0,
            buffer_min=0,
        )
    assert caught.value.reason == "slot_invalid"


def test_booking_text_templates_have_no_raw_times() -> None:
    for key in (
        "booking_confirmed",
        "offer_expired",
        "slot_taken",
        "slot_invalid",
        "offers_refreshed",
    ):
        text = CONVERSATION_TEXTS[key].replace("{label}", "")
        assert "[TO_APPROVE]" in CONVERSATION_TEXTS[key]
        assert ":" not in text or key == "booking_confirmed"
        assert "AM" not in text
        assert "PM" not in text
        assert "2026" not in text
