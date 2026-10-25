"""Safety trigger coverage using the reviewed YAML keyword source."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from coaching_inquiry_engine.domain.models import QualifyFlags
from coaching_inquiry_engine.domain.safety import SafetyKeywords, detect_triggers

_KEYWORDS_PATH = Path(__file__).resolve().parents[2] / "data" / "safety_keywords.yaml"
_CATEGORY_FLAGS = {
    "distress": "distress_detected",
    "self_harm": "self_harm",
    "minor_signal": "is_minor",
    "scam_request": "scam_signal",
    "fee_dispute": "fee_dispute",
    "complaint": "complaint",
    "human_request": "human_request",
    "injection_attempt": "injection_attempt",
}


@pytest.fixture(scope="module")
def keywords() -> SafetyKeywords:
    raw = yaml.safe_load(_KEYWORDS_PATH.read_text(encoding="utf-8"))
    return SafetyKeywords.model_validate(raw)


@pytest.mark.parametrize(
    ("category", "language"),
    [
        (category, language)
        for category in _CATEGORY_FLAGS
        for language in ("en", "hi", "hinglish")
    ],
)
def test_keyword_phrase_fires_category(
    keywords: SafetyKeywords, category: str, language: str
) -> None:
    phrase = getattr(keywords.categories[category], language)[0]
    flags = detect_triggers(phrase, keywords)

    assert getattr(flags, _CATEGORY_FLAGS[category]) is True


@pytest.mark.parametrize("category", _CATEGORY_FLAGS)
def test_benign_message_does_not_fire_category(
    keywords: SafetyKeywords, category: str
) -> None:
    flags = detect_triggers("Could you tell me about your course schedule?", keywords)

    assert getattr(flags, _CATEGORY_FLAGS[category]) is False


def test_benign_message_has_no_safety_flags(keywords: SafetyKeywords) -> None:
    flags = detect_triggers("Could you tell me about your course schedule?", keywords)

    assert flags == QualifyFlags()
