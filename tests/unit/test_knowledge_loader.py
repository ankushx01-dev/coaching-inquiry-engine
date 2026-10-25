"""Validation rules for institute and UPSC knowledge YAML."""

from __future__ import annotations

from datetime import date

import pytest
import yaml

from coaching_inquiry_engine.domain.knowledge import KnowledgeLoadError, load_knowledge


def _entry(**overrides: object) -> dict[str, object]:
    return {
        "id": "example_facts",
        "topic": "study_basics",
        "text": "Verified general preparation guidance.",
        "source_note": "Academic review",
        "source_url": "https://upsc.gov.in/",
        "last_verified": date(2026, 10, 20),
        "status": "VERIFIED",
        **overrides,
    }


def _write(path, entries: list[dict[str, object]], **overrides: object) -> None:
    payload: dict[str, object] = {
        "institute_name": "UPSC reference",
        "owner": "Academic head",
        "last_reviewed": date(2026, 10, 20),
        "status": "VERIFIED",
        "entries": entries,
        **overrides,
    }
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")


def test_valid_knowledge_file_loads(tmp_path) -> None:
    path = tmp_path / "upsc_reference.yaml"
    _write(path, [_entry()])

    loaded = load_knowledge(path)

    assert loaded.entries[0].id == "example_facts"


def test_unknown_entry_field_is_rejected_and_names_entry(tmp_path) -> None:
    path = tmp_path / "institute.yaml"
    _write(path, [_entry(unreviewed_value="not allowed")])

    with pytest.raises(KnowledgeLoadError, match="example_facts"):
        load_knowledge(path)


@pytest.mark.parametrize(
    ("topic", "text"),
    [
        ("study_basics", "The course fee is a fixed amount."),
        ("study_basics", "The examination date is listed in the notice."),
    ],
)
def test_unverified_fee_or_date_claim_is_rejected(
    tmp_path, topic: str, text: str
) -> None:
    path = tmp_path / "upsc_reference.yaml"
    _write(
        path,
        [_entry(topic=topic, text=text, status="TO_VERIFY", last_verified=None)],
        status="TO_VERIFY",
    )

    with pytest.raises(KnowledgeLoadError, match="example_facts"):
        load_knowledge(path)


def test_non_upsc_source_url_is_rejected(tmp_path) -> None:
    path = tmp_path / "upsc_reference.yaml"
    _write(path, [_entry(source_url="https://example.org/facts")])

    with pytest.raises(KnowledgeLoadError, match="example_facts"):
        load_knowledge(path)


def test_benchmark_file_is_refused_on_answering_path(tmp_path) -> None:
    path = tmp_path / "drishti_ias.yaml"
    _write(
        path,
        [_entry(status="TO_VERIFY", last_verified=None)],
        usage="benchmark_only",
    )

    with pytest.raises(KnowledgeLoadError, match="benchmark-only"):
        load_knowledge(path)
