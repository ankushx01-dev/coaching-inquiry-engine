"""Pure helpers for deterministic chat menu and open-question routing."""

from __future__ import annotations

import re
import unicodedata

from coaching_inquiry_engine.domain.models import (
    Stage,
    Target,
    Timeline,
    normalize_person_name,
)

_HUMAN_REQUESTS = (
    "counsellor",
    "counselor",
    "talk to an agent",
    "speak to an agent",
    "talk to a human",
    "speak to a human",
    "talk to someone",
    "speak to someone",
    "talk to a person",
    "speak to a person",
    "connect me to staff",
)
_PREDICTION_TERMS = (
    "can i crack",
    "will i crack",
    "can i clear",
    "will i clear",
    "can i pass",
    "will i pass",
    "chance of selection",
    "predict my result",
    "selection hoga",
    "exam crack kar paunga",
)


def normalize_chat_text(text: str) -> str:
    kept = [
        character
        for character in text.casefold()
        if not unicodedata.category(character).startswith(("P", "S"))
    ]
    return re.sub(r"\s+", " ", "".join(kept)).strip()


def is_human_request(text: str) -> bool:
    normalized = normalize_chat_text(text)
    return any(phrase in normalized for phrase in _HUMAN_REQUESTS)


def is_prediction_question(text: str) -> bool:
    normalized = normalize_chat_text(text)
    return any(phrase in normalized for phrase in _PREDICTION_TERMS)


def extract_name(text: str) -> str | None:
    match = re.search(
        r"\b(?:my name is|i am|i'm|mera naam)\s+([A-Za-z][A-Za-z .'-]{0,58})",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    candidate = match.group(1).strip(" .,'-\t\r\n")
    if not candidate or len(candidate.split()) > 4:
        return None
    try:
        return normalize_person_name(candidate)
    except ValueError:
        return None


def parse_stage(text: str) -> Stage | None:
    normalized = normalize_chat_text(text)
    if any(
        term in normalized
        for term in ("first attempt", "beginner", "new to prep")
    ):
        return Stage.first_attempt
    if any(
        term in normalized
        for term in ("reattempt", "re attempt", "again", "second attempt")
    ):
        return Stage.reattempt
    if any(
        term in normalized
        for term in ("working professional", "working full time", "job")
    ):
        return Stage.working_professional
    return None


def parse_target(text: str) -> Target | None:
    normalized = normalize_chat_text(text)
    if "test series" in normalized:
        return Target.test_series
    if "full course" in normalized or "complete course" in normalized:
        return Target.full_course
    if "mains" in normalized:
        return Target.mains
    if "prelims" in normalized:
        return Target.prelims
    return None


def parse_timeline(text: str) -> Timeline | None:
    normalized = normalize_chat_text(text)
    if any(
        term in normalized
        for term in ("within 1 month", "this month", "next month")
    ):
        return Timeline.within_1_month
    if "within 3 months" in normalized or "three months" in normalized:
        return Timeline.within_3_months
    if any(term in normalized for term in ("later", "not sure", "after six months")):
        return Timeline.later
    return None
