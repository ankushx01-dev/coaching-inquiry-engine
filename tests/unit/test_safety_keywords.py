"""Validation tests for YAML safety keyword data."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from coaching_inquiry_engine.domain.safety import SafetyKeywords


def _load_keywords(path: Path) -> SafetyKeywords:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return SafetyKeywords.model_validate(raw)


def test_loader_rejects_empty_category(tmp_path: Path) -> None:
    path = tmp_path / "empty-category.yaml"
    path.write_text(
        "review_status: PENDING_ACADEMIC_HEAD_REVIEW\n"
        "categories:\n"
        "  distress:\n"
        "    en: []\n"
        "    hi: []\n"
        "    hinglish: []\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as exc_info:
        _load_keywords(path)
    assert "distress" in str(exc_info.value)
    assert "en" in str(exc_info.value)


@pytest.mark.parametrize("empty_language", ["en", "hi", "hinglish"])
def test_loader_rejects_each_empty_language_list(
    tmp_path: Path, empty_language: str
) -> None:
    phrases = {
        "en": ["I feel hopeless"],
        "hi": ["मैं बहुत परेशान हूँ"],
        "hinglish": ["bahut pareshaan hoon"],
    }
    phrases[empty_language] = []
    path = tmp_path / f"empty-{empty_language}.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "review_status": "PENDING_ACADEMIC_HEAD_REVIEW",
                "categories": {"distress": phrases},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as exc_info:
        _load_keywords(path)

    assert "distress" in str(exc_info.value)
    assert empty_language in str(exc_info.value)


def test_loader_rejects_missing_review_status(tmp_path: Path) -> None:
    path = tmp_path / "missing-review-status.yaml"
    path.write_text(
        "categories:\n"
        "  distress:\n"
        "    en: [\"I feel hopeless\"]\n"
        "    hi: [\"मैं बहुत परेशान हूँ\"]\n"
        "    hinglish: [\"bahut pareshaan hoon\"]\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        _load_keywords(path)
