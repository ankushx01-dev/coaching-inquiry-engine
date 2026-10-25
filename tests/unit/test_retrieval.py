"""Verified knowledge retrieval uses simple keyword overlap only."""

from __future__ import annotations

from datetime import date

from coaching_inquiry_engine.domain.knowledge import KnowledgeEntry
from coaching_inquiry_engine.domain.retrieval import retrieve


def _entry(
    identifier: str,
    topic: str,
    text: str,
    status: str = "VERIFIED",
) -> KnowledgeEntry:
    return KnowledgeEntry(
        id=identifier,
        topic=topic,
        text=text,
        source_note="Reviewed source",
        last_verified=date(2026, 10, 20) if status == "VERIFIED" else None,
        status=status,
    )


def test_matching_topic_returns_entry() -> None:
    entries = [_entry("fees", "fees", "Course fee details are reviewed.")]

    matches = retrieve(["fees"], entries, topic_keywords={"fees": ["fee", "fees"]})

    assert [match.entry.id for match in matches] == ["fees"]


def test_to_verify_entries_are_never_returned() -> None:
    entries = [_entry("fees", "fees", "Fee information", status="TO_VERIFY")]

    assert retrieve(["fees"], entries, topic_keywords={"fees": ["fees"]}) == []


def test_no_match_returns_empty_list() -> None:
    entries = [_entry("batches", "batches", "Batch information")]

    assert retrieve(["location"], entries) == []


def test_retrieval_returns_at_most_three_entries() -> None:
    entries = [
        _entry(f"study_{index}", "study_basics", f"Study preparation {index}")
        for index in range(5)
    ]

    assert len(retrieve(["study", "preparation"], entries)) == 3
