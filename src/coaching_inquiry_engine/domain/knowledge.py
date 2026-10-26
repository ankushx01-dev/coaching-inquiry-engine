"""Validated, reviewable knowledge files for the answering layer."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationError,
    model_validator,
)

KnowledgeTopic = Literal[
    "batches",
    "fees",
    "timings",
    "demo_classes",
    "faculty",
    "location",
    "contact",
    "faq",
    "exam_structure",
    "prelims_overview",
    "mains_overview",
    "interview_overview",
    "study_basics",
    "eligibility",
    "age_limit",
    "attempts",
    "exam_pattern",
    "syllabus",
    "important_dates",
    "institute_batches",
    "institute_fees",
]
KnowledgeStatus = Literal["VERIFIED", "TO_VERIFY"]


class CourseInfoEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)
    status: KnowledgeStatus
    last_verified: date | None = None
    available: bool | None = None
    mode: Literal["online", "offline", "hybrid"] | None = None
    schedule: str | None = None


UPSC_TOPICS = frozenset(
    {
        "exam_structure",
        "prelims_overview",
        "mains_overview",
        "interview_overview",
        "study_basics",
    }
)
_SENSITIVE_UPSC_CLAIM = re.compile(
    r"\b(date|dates|age|ages|fee|fees|attempt|attempts|vacancy|vacancies)\b|\d",
    re.IGNORECASE,
)


class KnowledgeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    topic: KnowledgeTopic
    text: str = Field(min_length=1)
    source_note: str = Field(min_length=1)
    source_url: HttpUrl | None = None
    last_verified: date | None = None
    status: KnowledgeStatus

    @model_validator(mode="after")
    def verified_requires_date(self) -> Self:
        if self.status == "VERIFIED" and self.last_verified is None:
            raise ValueError("VERIFIED status requires last_verified")
        return self


class KnowledgeFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    institute_name: str = Field(min_length=1)
    display_name: str | None = None
    owner: str = Field(min_length=1)
    last_reviewed: date
    status: KnowledgeStatus
    timezone: str | None = None
    usage: Literal["benchmark_only"] | None = None
    entries: list[KnowledgeEntry]
    courses: dict[str, dict[str, CourseInfoEntry | str]] = Field(
        default_factory=dict
    )

    @classmethod
    def validate_upsc_claims(cls, entries: list[KnowledgeEntry]) -> None:
        for entry in entries:
            if entry.topic not in UPSC_TOPICS:
                continue
            if (
                _SENSITIVE_UPSC_CLAIM.search(entry.text) is not None
                and (entry.status != "VERIFIED" or entry.last_verified is None)
            ):
                raise ValueError(
                    f"entry {entry.id}: date, age, fee, attempts, and vacancy "
                    "claims require VERIFIED status and last_verified"
                )

    def check_upsc_claims(self) -> Self:
        self.validate_upsc_claims(self.entries)
        return self


class KnowledgeLoadError(ValueError):
    """Raised when a knowledge file is invalid or not answerable."""


def load_knowledge(path: Path | str) -> KnowledgeFile:
    """Load a knowledge file, reporting the offending entry id on validation errors."""
    source_path = Path(path)
    try:
        raw = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise KnowledgeLoadError(
            f"could not load knowledge file {source_path}"
        ) from exc
    try:
        knowledge = KnowledgeFile.model_validate(raw)
        knowledge.check_upsc_claims()
        for entry in knowledge.entries:
            if entry.topic in UPSC_TOPICS:
                host = entry.source_url.host if entry.source_url is not None else None
                if host is None or not (
                    host.casefold() == "upsc.gov.in"
                    or host.casefold().endswith(".upsc.gov.in")
                ):
                    raise ValueError(
                        f"entry {entry.id}: source_url must use upsc.gov.in"
                    )
        entry_ids = [entry.id for entry in knowledge.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("knowledge entry ids must be unique")
    except (ValidationError, ValueError) as exc:
        entry_id = _error_entry_id(exc, raw)
        raise KnowledgeLoadError(
            f"invalid knowledge entry {entry_id}: {exc}"
        ) from exc
    if knowledge.usage == "benchmark_only":
        raise KnowledgeLoadError(
            "benchmark-only knowledge cannot be loaded for answering"
        )
    return knowledge


def _error_entry_id(exc: Exception, raw: object) -> str:
    if isinstance(raw, dict):
        for error in getattr(exc, "errors", lambda: [])():
            loc = error.get("loc", ())
            if len(loc) > 1 and isinstance(loc[0], int):
                entries = raw.get("entries")
                if isinstance(entries, list) and loc[0] < len(entries):
                    item = entries[loc[0]]
                    if isinstance(item, dict) and item.get("id") is not None:
                        return str(item["id"])
        entries = raw.get("entries")
        if isinstance(entries, list) and entries and isinstance(entries[0], dict):
            return str(entries[0].get("id", "<unknown>"))
    match = re.search(r"entry ([^:]+):", str(exc))
    return match.group(1) if match else "<file>"
