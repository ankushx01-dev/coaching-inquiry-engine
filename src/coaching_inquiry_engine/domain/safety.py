"""Safety trigger detection and response planning. Pure domain logic, no I/O."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, field_validator

from coaching_inquiry_engine.domain.models import QualifyFlags

# ---------------------------------------------------------------------------
# NOTE: QualifyFlags in domain/models.py must be extended with:
#   self_harm: bool = False
#   human_request: bool = False
#   injection_attempt: bool = False
# This module assumes those fields exist.
# ---------------------------------------------------------------------------

# Regex patterns for PII masking
_PHONE_PATTERN = re.compile(r"\d[\d\s\-]{8,}\d")
_EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)

# Characters stripped from word edges during normalisation
_EDGE_PUNCTUATION = frozenset(".,!?;:")

# Mapping from YAML category name -> QualifyFlags field name
_CATEGORY_TO_FLAG: dict[str, str] = {
    "distress": "distress_detected",
    "self_harm": "self_harm",
    "minor_signal": "is_minor",
    "scam_request": "scam_signal",
    "fee_dispute": "fee_dispute",
    "complaint": "complaint",
    "human_request": "human_request",
    "injection_attempt": "injection_attempt",
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class CategoryPhrases(BaseModel):
    """Keyword phrases for a single safety category across languages."""

    model_config = ConfigDict(extra="forbid")

    en: list[str]
    hi: list[str]
    hinglish: list[str]


class SafetyKeywords(BaseModel):
    """Loaded keyword data from YAML. Validated at startup."""

    model_config = ConfigDict(extra="forbid")

    review_status: str
    categories: dict[str, CategoryPhrases]

    @field_validator("categories")
    @classmethod
    def require_phrases_for_each_language(
        cls, categories: dict[str, CategoryPhrases]
    ) -> dict[str, CategoryPhrases]:
        for category, phrases in categories.items():
            for language, entries in (
                ("en", phrases.en),
                ("hi", phrases.hi),
                ("hinglish", phrases.hinglish),
            ):
                if not entries:
                    raise ValueError(
                        f"category '{category}' has an empty '{language}' phrase list"
                    )
        return categories


class ActionPlan(BaseModel):
    """Describes what the system should do in response to safety flags."""

    model_config = ConfigDict(extra="forbid")

    text_key: str | None = None
    notify_staff: bool = False
    reason: str | None = None
    block_sales: bool = False
    block_data_collection: bool = False


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def _normalise_text(text: str) -> str:
    """Lower-case, collapse whitespace, strip edge punctuation from words."""
    lowered = text.lower()
    collapsed = re.sub(r"\s+", " ", lowered).strip()
    return collapsed


def _normalise_phrase(phrase: str) -> str:
    """Normalise a keyword phrase for matching."""
    return _normalise_text(phrase)


def _strip_edge_punct(word: str) -> str:
    """Remove common punctuation from the start and end of a word."""
    while word and word[0] in _EDGE_PUNCTUATION:
        word = word[1:]
    while word and word[-1] in _EDGE_PUNCTUATION:
        word = word[:-1]
    return word


def _text_contains_phrase(normalised_text: str, phrase: str) -> bool:
    """Check whether *normalised_text* contains the normalised *phrase*.

    Both single-word and multi-word phrases are supported.  For single-word
    phrases we also try matching against individually punctuation-stripped
    words so that ``"help!"`` matches the keyword ``"help"``.
    """
    norm_phrase = _normalise_phrase(phrase)
    if not norm_phrase:
        return False

    # Direct substring check (covers multi-word phrases)
    if norm_phrase in normalised_text:
        return True

    # For single-word keywords, also check after stripping edge punctuation
    if " " not in norm_phrase:
        words = normalised_text.split()
        return any(_strip_edge_punct(w) == norm_phrase for w in words)

    return False


def detect_triggers(text: str, keywords: SafetyKeywords) -> QualifyFlags:
    """Scan *text* for safety-related phrases and return matching flags.

    The function is **pure** – no I/O.  It performs case-insensitive
    matching with whitespace normalisation and strips common edge
    punctuation (periods, commas, exclamation marks, etc.).

    Each category in *keywords.categories* is checked across all three
    language lists (``en``, ``hi``, ``hinglish``).  The detected
    categories are mapped to :class:`QualifyFlags` fields via
    ``_CATEGORY_TO_FLAG``.
    """
    normalised = _normalise_text(text)
    matched_flags: dict[str, bool] = {}

    for category_name, phrases in keywords.categories.items():
        flag_field = _CATEGORY_TO_FLAG.get(category_name)
        if flag_field is None:
            # Unknown category – skip silently (forward-compatible).
            continue

        all_phrases: list[str] = phrases.en + phrases.hi + phrases.hinglish
        for phrase in all_phrases:
            if _text_contains_phrase(normalised, phrase):
                matched_flags[flag_field] = True
                break  # One match per category is enough.

    return QualifyFlags(**matched_flags)


def plan_response(flags: QualifyFlags) -> ActionPlan:
    """Choose an :class:`ActionPlan` based on a snapshot of safety *flags*.

    Priority order (first match wins):

    1. ``self_harm`` or ``distress_detected``
    2. ``is_minor``
    3. ``scam_signal``
    4. ``fee_dispute`` or ``complaint``
    5. ``human_request``
    6. ``injection_attempt``
    7. No flags → empty plan.

    .. note::

       ``plan_response`` does **not** duplicate lead-status logic (handled
       by :func:`qualify`).  It only selects the response text key and
       staff notification behaviour.

       For ``injection_attempt``, ``notify_staff`` is always ``False``
       because escalation on repeated attempts is the caller's
       responsibility (services layer).
    """
    if flags.self_harm or flags.distress_detected:
        return ActionPlan(
            text_key="distress_support",
            notify_staff=True,
            block_sales=True,
            reason="distress_or_self_harm",
        )

    if flags.is_minor:
        return ActionPlan(
            text_key="minor_guardian",
            notify_staff=True,
            block_data_collection=True,
            reason="minor_linked",
        )

    if flags.scam_signal:
        return ActionPlan(
            text_key="scam_warning",
            notify_staff=True,
            block_sales=True,
            reason="scam_signal",
        )

    if flags.fee_dispute or flags.complaint:
        return ActionPlan(
            text_key="fee_dispute_handoff",
            notify_staff=True,
            reason="fee_dispute_or_complaint",
        )

    if flags.human_request:
        return ActionPlan(
            text_key="human_handoff",
            notify_staff=True,
            reason="human_request",
        )

    if flags.injection_attempt:
        return ActionPlan(
            text_key="injection_decline",
            notify_staff=False,
            reason="injection_attempt",
        )

    return ActionPlan()


def mask_for_staff(text: str) -> str:
    """Mask phone numbers (10+ digit runs) and email addresses in *text*.

    Returns a copy of *text* with sensitive patterns replaced by
    ``[MASKED]``.
    """
    masked = _EMAIL_PATTERN.sub("[MASKED]", text)
    masked = _PHONE_PATTERN.sub("[MASKED]", masked)
    return masked
