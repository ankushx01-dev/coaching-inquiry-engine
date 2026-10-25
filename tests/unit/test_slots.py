"""Pure slot generation. Callers pass `now`; domain never reads the clock."""

from __future__ import annotations

import ast
from datetime import datetime, time, timedelta
from pathlib import Path

from coaching_inquiry_engine.domain.config import BOOKING_TZ, BUSINESS_HOURS
from coaching_inquiry_engine.domain.slots import candidate_slots, format_slot_label

_DOMAIN = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "coaching_inquiry_engine"
    / "domain"
)
_MONDAY_MORNING = datetime(2026, 10, 26, 8, 0, tzinfo=BOOKING_TZ)
_HOURS = dict(BUSINESS_HOURS)
_DURATION = 30


def _slots(**overrides: object) -> list:
    params: dict[str, object] = {
        "now": _MONDAY_MORNING,
        "tz": BOOKING_TZ,
        "hours": _HOURS,
        "busy": (),
        "duration_min": _DURATION,
        "days": 1,
        "limit": 20,
        "lead_min": 0,
        "buffer_min": 0,
    }
    params.update(overrides)
    return candidate_slots(**params)  # type: ignore[arg-type]


def test_slots_are_inside_business_hours() -> None:
    slots = _slots()
    assert slots
    for slot in slots:
        local = slot.start.astimezone(BOOKING_TZ)
        assert local.weekday() == 0
        assert time(10, 0) <= local.time()
        end = local + timedelta(minutes=slot.duration_min)
        assert end.time() <= time(18, 0)
        assert end.date() == local.date()


def test_slots_ending_after_closing_are_excluded() -> None:
    slots = _slots(duration_min=60, step_min=30)
    local_starts = [slot.start.astimezone(BOOKING_TZ).time() for slot in slots]
    assert time(17, 0) in local_starts
    assert time(17, 30) not in local_starts
    for slot in slots:
        end = slot.start.astimezone(BOOKING_TZ) + timedelta(minutes=60)
        assert end.time() <= time(18, 0)


def test_busy_intervals_are_avoided() -> None:
    busy_start = datetime(2026, 10, 26, 11, 0, tzinfo=BOOKING_TZ)
    busy_end = datetime(2026, 10, 26, 12, 0, tzinfo=BOOKING_TZ)
    slots = _slots(busy=((busy_start, busy_end),), buffer_min=15)
    for slot in slots:
        start = slot.start.astimezone(BOOKING_TZ)
        end = start + timedelta(minutes=_DURATION)
        blocked_start = busy_start - timedelta(minutes=15)
        blocked_end = busy_end + timedelta(minutes=15)
        assert not (start < blocked_end and end > blocked_start)


def test_lead_time_is_respected() -> None:
    now = datetime(2026, 10, 26, 10, 0, tzinfo=BOOKING_TZ)
    slots = _slots(now=now, lead_min=120)
    assert slots
    earliest = now + timedelta(minutes=120)
    assert all(slot.start >= earliest.astimezone(slot.start.tzinfo) for slot in slots)
    first_local = slots[0].start.astimezone(BOOKING_TZ)
    assert first_local.hour >= 12


def test_results_are_sorted_and_capped_at_limit() -> None:
    slots = _slots(limit=3)
    assert len(slots) == 3
    starts = [slot.start for slot in slots]
    assert starts == sorted(starts)


def test_sunday_with_closed_hours_returns_no_slots() -> None:
    sunday = datetime(2026, 10, 25, 8, 0, tzinfo=BOOKING_TZ)
    assert sunday.weekday() == 6
    slots = _slots(now=sunday, days=1)
    assert slots == []


def test_format_slot_label_is_the_only_time_text() -> None:
    start = datetime(2026, 10, 27, 11, 0, tzinfo=BOOKING_TZ)
    label = format_slot_label(start, BOOKING_TZ)
    assert label == "Tuesday 27 Oct, 11:00 AM IST"


def test_domain_has_no_vendor_imports() -> None:
    forbidden = {"google", "httpx", "sqlalchemy", "fastapi"}
    imported: set[str] = set()
    for path in _DOMAIN.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(forbidden)


def test_domain_has_no_datetime_now_or_time_time_calls() -> None:
    clock_calls: list[str] = []
    for path in _DOMAIN.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                owner = func.value
                owner_name = owner.id if isinstance(owner, ast.Name) else ""
                if owner_name == "datetime" and func.attr in {"now", "utcnow"}:
                    clock_calls.append(f"{path.name}:{func.attr}")
                if owner_name == "time" and func.attr == "time":
                    clock_calls.append(f"{path.name}:time.time")
            elif isinstance(func, ast.Name) and func.id in {"now", "utcnow"}:
                clock_calls.append(f"{path.name}:{func.id}")
    assert clock_calls == []
