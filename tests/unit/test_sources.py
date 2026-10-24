"""Unit tests for the approved-sources registry."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from coaching_inquiry_engine.domain.config import FALLBACK_TEXTS
from coaching_inquiry_engine.domain.sources import (
    Found,
    Missing,
    SourceEntry,
    SourceLoadError,
    Stale,
    get_source,
    load_sources,
)

_TODAY = date(2026, 10, 24)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHIPPED_YAML = _REPO_ROOT / "data" / "approved_sources.yaml"
_ANSWER_SUMMARY_LITERAL = re.compile(
    r"answer_summary\s*[:=]\s*(['\"])(?P<body>.*?)\1",
    re.DOTALL,
)


def _entry(
    *,
    status: str = "VERIFIED",
    last_verified: date | None = date(2026, 10, 10),
    answer_summary: str | None = "PLACEHOLDER not an official fact",
    official_url: str = "https://upsc.gov.in/",
    topic: str = "eligibility",
    entry_id: str = "eligibility",
    owner: str = "upsc",
) -> SourceEntry:
    return SourceEntry(
        id=entry_id,
        topic=topic,  # type: ignore[arg-type]
        official_url=official_url,  # type: ignore[arg-type]
        answer_summary=answer_summary,
        last_verified=last_verified,
        owner=owner,
        status=status,  # type: ignore[arg-type]
    )


def test_verified_fresh_entry_returns_found_with_official_url() -> None:
    entry = _entry(official_url="https://upsc.gov.in/examinations")
    result = get_source({entry.topic: entry}, entry.topic, _TODAY)
    assert isinstance(result, Found)
    assert str(result.entry.official_url) == str(entry.official_url)
    assert result.entry.official_url.host == "upsc.gov.in"


def test_verified_entry_older_than_30_days_returns_stale() -> None:
    entry = _entry(last_verified=date(2026, 9, 1))
    result = get_source({entry.topic: entry}, entry.topic, _TODAY)
    assert isinstance(result, Stale)
    assert result.entry.id == entry.id


def test_to_verify_entry_returns_missing_even_with_recent_date() -> None:
    entry = _entry(status="TO_VERIFY", last_verified=date(2026, 10, 20))
    result = get_source({entry.topic: entry}, entry.topic, _TODAY)
    assert result == Missing(entry.topic)


def test_unknown_topic_returns_missing() -> None:
    entry = _entry()
    result = get_source({entry.topic: entry}, "syllabus", _TODAY)
    assert result == Missing("syllabus")


def test_non_upsc_host_fails_validation() -> None:
    with pytest.raises(ValidationError):
        _entry(official_url="https://example.com/eligibility")


def test_upsc_subdomain_passes_validation() -> None:
    entry = _entry(official_url="https://www.upsc.gov.in/examinations")
    assert entry.official_url.host == "www.upsc.gov.in"


def test_verified_status_with_null_answer_summary_fails_validation() -> None:
    with pytest.raises(ValidationError):
        _entry(answer_summary=None, last_verified=date(2026, 10, 10), status="VERIFIED")


def test_invalid_yaml_entry_raises_error_naming_its_id(tmp_path: Path) -> None:
    path = tmp_path / "bad_sources.yaml"
    path.write_text(
        """
sources:
  - id: bad_fees
    topic: fees
    official_url: https://example.com/not-upsc
    answer_summary: null
    last_verified: null
    owner: upsc
    status: TO_VERIFY
""",
        encoding="utf-8",
    )
    with pytest.raises(SourceLoadError, match="bad_fees"):
        load_sources(path)


def test_no_upsc_facts_in_answer_summary_defaults() -> None:
    src_root = _REPO_ROOT / "src"
    for path in src_root.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".yaml", ".yml"}:
            continue
        text = path.read_text(encoding="utf-8")
        for match in _ANSWER_SUMMARY_LITERAL.finditer(text):
            body = match.group("body")
            assert not any(char.isdigit() for char in body), (
                f"digits in answer_summary default in {path}"
            )


def test_shipped_yaml_contains_zero_verified_facts() -> None:
    registry = load_sources(_SHIPPED_YAML)
    assert set(registry) == {
        "eligibility",
        "age_limit",
        "attempts",
        "exam_pattern",
        "syllabus",
        "important_dates",
        "fees",
        "institute_batches",
        "institute_fees",
    }
    for entry in registry.values():
        assert entry.status == "TO_VERIFY"
        assert entry.answer_summary is None
        assert entry.last_verified is None


def test_fallback_texts_are_placeholders() -> None:
    assert "TO_APPROVE" in FALLBACK_TEXTS["stale"]
    assert "TO_APPROVE" in FALLBACK_TEXTS["missing"]
    assert not any(char.isdigit() for char in FALLBACK_TEXTS["stale"])
    assert not any(char.isdigit() for char in FALLBACK_TEXTS["missing"])
