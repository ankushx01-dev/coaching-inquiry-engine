"""BookingService with FakeCalendar and an in-memory store."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from coaching_inquiry_engine.adapters.booking_memory import (
    MemoryBookingStore,
    OutboxInsertError,
)
from coaching_inquiry_engine.adapters.calendar_fake import FakeCalendar
from coaching_inquiry_engine.domain.config import BOOKING_TZ
from coaching_inquiry_engine.domain.decisions import (
    AgentDecision,
    NextAction,
    SlotOption,
    booking_choice_index,
)
from coaching_inquiry_engine.ports.llm import DecisionContext
from coaching_inquiry_engine.services.booking_service import BookingService

_NOW = datetime(2026, 10, 26, 8, 0, tzinfo=BOOKING_TZ)


def _service() -> tuple[BookingService, FakeCalendar, MemoryBookingStore]:
    calendar = FakeCalendar()
    store = MemoryBookingStore()
    return BookingService(calendar, store), calendar, store


def _choice(index: int) -> AgentDecision:
    return AgentDecision(
        next_action=NextAction.booking_choice,
        reply_text="Confirming the offered slot.",
        booking_choice_index=index,
        prompt_version="upsc_v0.2",
    )


async def test_tapping_the_same_offer_twice_creates_exactly_one_event() -> None:
    service, calendar, _store = _service()
    lead_id = uuid4()
    await service.create_offers(lead_id, _NOW)
    offer_id = next(
        offer.id for offer in _store.offers.values() if offer.option_index == 0
    )
    first = await service.book_offer(lead_id, 0, _NOW)
    second = await service.book_offer(lead_id, offer_id, _NOW)
    assert first.ok is True
    assert first.text_key == "booking_confirmed"
    assert second.ok is False
    assert second.reason == "offer_used"
    assert calendar.create_event_calls == 1
    assert len(calendar.event_ids) == 1


async def test_expired_offer_is_rejected_and_no_event_is_created() -> None:
    service, calendar, _store = _service()
    lead_id = uuid4()
    await service.create_offers(lead_id, _NOW)
    later = _NOW + timedelta(minutes=31)
    result = await service.book_offer(lead_id, 0, later)
    assert result.ok is False
    assert result.reason == "offer_expired"
    assert result.text_key == "offer_expired"
    assert calendar.create_event_calls == 0


async def test_offer_belonging_to_another_lead_is_rejected() -> None:
    service, calendar, store = _service()
    owner = uuid4()
    other = uuid4()
    await service.create_offers(owner, _NOW)
    offer_id = next(iter(store.offers))
    result = await service.book_offer(other, offer_id, _NOW)
    assert result.ok is False
    assert result.reason == "offer_wrong_lead"
    assert calendar.create_event_calls == 0


async def test_used_offer_is_rejected() -> None:
    service, calendar, store = _service()
    lead_id = uuid4()
    await service.create_offers(lead_id, _NOW)
    offer_id = next(iter(store.offers))
    first = await service.book_offer(lead_id, offer_id, _NOW)
    second = await service.book_offer(lead_id, offer_id, _NOW)
    assert first.ok is True
    assert second.ok is False
    assert second.reason == "offer_used"
    assert calendar.create_event_calls == 1


async def test_busy_added_between_create_and_book_is_slot_taken() -> None:
    service, calendar, store = _service()
    lead_id = uuid4()
    await service.create_offers(lead_id, _NOW)
    assert calendar.busy_interval_calls == 1
    offer = next(offer for offer in store.offers.values() if offer.option_index == 0)
    calendar.add_busy(
        offer.start, offer.start + timedelta(minutes=offer.duration_min)
    )
    result = await service.book_offer(lead_id, 0, _NOW)
    assert result.ok is False
    assert result.reason == "slot_taken"
    assert result.text_key == "slot_taken"
    assert calendar.busy_interval_calls == 2
    assert calendar.create_event_calls == 0


async def test_booking_choice_index_without_active_offer_creates_no_event() -> None:
    service, calendar, _store = _service()
    result = await service.book_from_decision(uuid4(), _choice(1), _NOW)
    assert result.ok is False
    assert result.reason == "offer_not_found"
    assert calendar.create_event_calls == 0


async def test_outbox_failure_retry_does_not_create_a_second_event() -> None:
    service, calendar, store = _service()
    lead_id = uuid4()
    await service.create_offers(lead_id, _NOW)
    store.fail_outbox_once = True
    with pytest.raises(OutboxInsertError):
        await service.book_offer(lead_id, 0, _NOW)
    assert calendar.create_event_calls == 1
    assert len(calendar.event_ids) == 1
    retry = await service.book_offer(lead_id, 0, _NOW)
    assert retry.ok is True
    assert calendar.create_event_calls == 2
    assert len(calendar.event_ids) == 1


async def test_create_offers_returns_index_and_label_only() -> None:
    service, _calendar, _store = _service()
    offers = await service.create_offers(uuid4(), _NOW)
    assert offers
    for offer in offers:
        dumped = offer.model_dump()
        assert set(dumped) == {"index", "label"}
        assert isinstance(offer.index, int)
        assert isinstance(offer.label, str)
        assert "T10:" not in offer.label
        assert "2026-10-26T" not in offer.label
        assert offer.label.count(":") == 1


def test_booking_choice_index_is_not_a_calendar_time() -> None:
    decision = _choice(1)
    assert booking_choice_index(decision) == 1
    ask = AgentDecision(
        next_action=NextAction.ask_field,
        reply_text="Which stage of preparation are you in?",
        prompt_version="upsc_v0.2",
    )
    assert booking_choice_index(ask) is None


def test_decision_context_slot_options_reject_datetimes() -> None:
    option = SlotOption(index=0, label="Monday 26 Oct, 10:00 AM IST")
    context = DecisionContext(
        messages=[],
        allowed_next_actions=[NextAction.booking_choice],
        slot_options=[option],
    )
    payload = context.model_dump()
    assert payload["slot_options"] == [{"index": 0, "label": option.label}]
    with pytest.raises(ValidationError):
        SlotOption.model_validate(
            {"index": 0, "label": "x", "start": _NOW.isoformat()}
        )
