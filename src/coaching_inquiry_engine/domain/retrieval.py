"""Term-overlap retrieval over already validated knowledge."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from coaching_inquiry_engine.domain.knowledge import KnowledgeEntry, KnowledgeFile

_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "are",
        "is",
        "the",
        "to",
        "what",
        "when",
        "where",
        "which",
        "me",
        "you",
        "i",
        "tell",
        "about",
    }
)

@dataclass(frozen=True, slots=True)
class RetrievedEntry:
    entry: KnowledgeEntry
    stale: bool


def retrieve(
    question_terms: Sequence[str] | set[str],
    knowledge: KnowledgeFile | Sequence[KnowledgeEntry],
    *,
    topic_keywords: Mapping[str, Sequence[str]] | None = None,
    today: date | None = None,
    max_age_days: int = 30,
) -> list[RetrievedEntry]:
    """Return up to three verified entries ranked by term overlap."""
    entries = knowledge.entries if isinstance(knowledge, KnowledgeFile) else knowledge
    terms = {
        token
        for term in question_terms
        for token in _tokens(term)
        if token and token not in _STOP_WORDS
    }
    if not terms:
        return []
    current_date = today or date.min
    candidates: list[tuple[int, int, RetrievedEntry]] = []
    for index, entry in enumerate(entries):
        if entry.status != "VERIFIED":
            continue
        keywords = (topic_keywords or {}).get(entry.topic, ())
        searchable = {
            token
            for word in keywords
            for token in _tokens(word)
            if token not in _STOP_WORDS
        }
        searchable.update(_tokens(entry.topic))
        searchable.update(_tokens(entry.text))
        searchable.difference_update(_STOP_WORDS)
        overlap = len(terms & searchable)
        if overlap == 0:
            continue
        stale = (
            entry.last_verified is not None
            and (current_date - entry.last_verified).days > max_age_days
        )
        candidates.append((overlap, -index, RetrievedEntry(entry, stale)))
    candidates.sort(key=lambda result: (result[0], result[1]), reverse=True)
    return [result[2] for result in candidates[:3]]


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[^\W_]+", value.casefold()) if token}


def _normalize(value: str) -> str:
    return " ".join(_tokens(value))
