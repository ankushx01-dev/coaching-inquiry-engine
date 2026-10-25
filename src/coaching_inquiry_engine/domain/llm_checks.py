"""Post-validation of AgentDecision. Pure functions; no HTTP or vendor imports.

Time/date/price/percentage detection uses simple regular expressions:

- Times: ``4:30``, ``4.30 pm``, ``4pm``
- Dates: ``24/10/2026``, ``2026-10-24``
- Prices: ``₹5000``, ``Rs 5000``, ``5000/-``
- Percentages: ``20%``, ``20 percent``

Limits: spelled-out times ("four thirty"), relative dates ("tomorrow"),
bare integers that are not prices or percents, and Unicode times without
ASCII digits are not detected. Matching is substring-based against offered
slot labels and approved source text supplied by the caller.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from coaching_inquiry_engine.domain.decisions import AgentDecision, NextAction

_TIME = re.compile(
    r"\b(?:[01]?\d|2[0-3])[:.][0-5]\d(?:\s*[ap]\.?m\.?)?\b|\b(?:[1-9]|1[0-2])\s*[ap]\.?m\.?\b",
    re.IGNORECASE,
)
_DATE = re.compile(
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b",
)
_PRICE = re.compile(
    r"(?:₹|rs\.?\s*)\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s*/-",
    re.IGNORECASE,
)
_PERCENT = re.compile(
    r"\b\d+(?:\.\d+)?\s*%|\b\d+(?:\.\d+)?\s*percent\b",
    re.IGNORECASE,
)
_CREDENTIAL = re.compile(
    r"\b(?:password|otp|aadhaar|login)\b",
    re.IGNORECASE,
)
PERSONAL_DATA_REQUEST = re.compile(
    r"\b(date\s+of\s+birth|dob|birth\s*date|aadhaar|aadhar|passport|pan\s+card|"
    r"bank|account\s+number|password|otp)\b",
    re.IGNORECASE,
)
_FORBIDDEN_CLAIMS = (
    "guaranteed",
    "100%",
    "toppers from us",
)


class DecisionRejectedError(ValueError):
    """The decision failed a post-validation rule and must not be used."""


def check_decision(
    decision: AgentDecision,
    *,
    offered_indices: frozenset[int],
    allowed_snippets: Iterable[str] = (),
    required_citation_ids: Iterable[str] = (),
) -> None:
    """Raise DecisionRejectedError if the decision is unsafe to apply."""
    check_booking_choice(decision, offered_indices)
    check_unapproved_quantities(decision.reply_text, allowed_snippets)
    citation_ids = tuple(required_citation_ids)
    if decision.next_action is NextAction.answer_question and citation_ids:
        if not any(f"[{entry_id}]" in decision.reply_text for entry_id in citation_ids):
            raise DecisionRejectedError("reply_text must cite a retrieved entry id")
    if reply_requests_personal_data(decision.reply_text):
        raise DecisionRejectedError("reply_text requests personal data")
    check_credential_request(decision.reply_text)
    check_forbidden_claims(decision.reply_text)


def reply_requests_personal_data(reply_text: str) -> bool:
    """Return whether a reply asks for sensitive personal data."""
    return PERSONAL_DATA_REQUEST.search(reply_text) is not None


def check_booking_choice(
    decision: AgentDecision, offered_indices: frozenset[int]
) -> None:
    if decision.next_action is not NextAction.booking_choice:
        return
    if decision.booking_choice_index not in offered_indices:
        raise DecisionRejectedError(
            "booking_choice_index is not in the offered slot options"
        )


def check_unapproved_quantities(
    reply_text: str, allowed_snippets: Iterable[str]
) -> None:
    allowed = " ".join(allowed_snippets)
    for pattern in (_TIME, _DATE, _PRICE, _PERCENT):
        for match in pattern.finditer(reply_text):
            token = match.group(0)
            if token.lower() not in allowed.lower():
                raise DecisionRejectedError(
                    f"reply_text contains unapproved quantity {token!r}"
                )


def check_credential_request(reply_text: str) -> None:
    match = _CREDENTIAL.search(reply_text)
    if match is not None:
        raise DecisionRejectedError(
            f"reply_text requests a credential ({match.group(0)!r})"
        )


def check_forbidden_claims(reply_text: str) -> None:
    lowered = reply_text.lower()
    for phrase in _FORBIDDEN_CLAIMS:
        if phrase in lowered:
            raise DecisionRejectedError(
                f"reply_text contains forbidden claim {phrase!r}"
            )
