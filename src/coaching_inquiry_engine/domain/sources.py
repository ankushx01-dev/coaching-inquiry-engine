"""Approved-source registry and lookup. No I/O besides loading the YAML file."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic import ValidationError as PydanticValidationError

from coaching_inquiry_engine.domain.config import INSTITUTE_DOMAIN, UPSC_OFFICIAL_HOST

SourceTopic = Literal[
    "eligibility",
    "age_limit",
    "attempts",
    "exam_pattern",
    "syllabus",
    "important_dates",
    "fees",
    "institute_batches",
    "institute_fees",
]
SourceStatus = Literal["VERIFIED", "TO_VERIFY"]

INSTITUTE_TOPICS: frozenset[str] = frozenset({"institute_batches", "institute_fees"})


class SourceLoadError(ValueError):
    """Raised when an approved-source YAML entry fails validation."""


class SourceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    topic: SourceTopic
    official_url: HttpUrl
    answer_summary: str | None = Field(default=None, max_length=1000)
    last_verified: date | None = None
    owner: str
    status: SourceStatus
    exam_id: str | None = None

    @field_validator("official_url")
    @classmethod
    def reject_non_upsc_hosts(cls, url: HttpUrl, info: ValidationInfo) -> HttpUrl:
        topic = info.data.get("topic")
        if topic in INSTITUTE_TOPICS:
            return url
        if not _host_allowed(url, UPSC_OFFICIAL_HOST):
            raise ValueError(
                f"official_url host must be {UPSC_OFFICIAL_HOST} or a subdomain of it"
            )
        return url

    @field_validator("official_url")
    @classmethod
    def reject_non_institute_hosts(cls, url: HttpUrl, info: ValidationInfo) -> HttpUrl:
        topic = info.data.get("topic")
        if topic not in INSTITUTE_TOPICS:
            return url
        if not _host_allowed(url, INSTITUTE_DOMAIN):
            raise ValueError(
                f"official_url host must be {INSTITUTE_DOMAIN} or a subdomain of it"
            )
        return url

    @model_validator(mode="after")
    def verified_requires_summary_and_date(self) -> Self:
        if self.status == "VERIFIED" and (
            self.answer_summary is None or self.last_verified is None
        ):
            raise ValueError(
                "VERIFIED status requires answer_summary and last_verified"
            )
        return self


@dataclass(frozen=True, slots=True)
class Found:
    entry: SourceEntry


@dataclass(frozen=True, slots=True)
class Stale:
    entry: SourceEntry


@dataclass(frozen=True, slots=True)
class Missing:
    topic: str


type SourceLookup = Found | Stale | Missing


def load_sources(path: Path | str) -> dict[str, SourceEntry]:
    """Read YAML and validate every entry. Invalid entries name their id."""
    raw: object = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    rows = _extract_rows(raw)
    registry: dict[str, SourceEntry] = {}
    for item in rows:
        entry_id = _entry_id(item)
        try:
            entry = SourceEntry.model_validate(item)
        except PydanticValidationError as exc:
            raise SourceLoadError(f"invalid source entry {entry_id}: {exc}") from exc
        registry_key = (
            f"{entry.exam_id}:{entry.topic}"
            if entry.exam_id is not None
            else entry.topic
        )
        if registry_key in registry:
            raise SourceLoadError(
                f"invalid source entry {entry.id}: duplicate source key {registry_key}"
            )
        registry[registry_key] = entry
    return registry


def get_source(
    registry: Mapping[str, SourceEntry],
    topic: str,
    today: date,
    max_age_days: int = 30,
) -> SourceLookup:
    """Look up a topic without using exceptions for missing or stale data."""
    entry = registry.get(topic)
    if entry is None or entry.status != "VERIFIED" or entry.last_verified is None:
        return Missing(topic)
    age_days = (today - entry.last_verified).days
    if age_days > max_age_days:
        return Stale(entry)
    return Found(entry)


def _extract_rows(raw: object) -> list[object]:
    if isinstance(raw, dict) and "sources" in raw:
        raw = raw["sources"]
    if not isinstance(raw, list):
        raise SourceLoadError("approved sources YAML must contain a list of entries")
    return raw


def _entry_id(item: object) -> str:
    if isinstance(item, dict) and item.get("id") is not None:
        return str(item["id"])
    return "<unknown>"


def _host_allowed(url: HttpUrl, root: str) -> bool:
    host = (url.host or "").lower().rstrip(".")
    allowed = root.lower().rstrip(".")
    return host == allowed or host.endswith("." + allowed)
