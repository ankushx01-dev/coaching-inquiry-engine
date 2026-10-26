"""Validated exam and category menu data."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

ExamCategoryId = Literal[
    "engineering_medical",
    "civil_services",
    "government_banking",
    "defence_officer",
    "agnipath",
]


class ExamCategory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category_id: ExamCategoryId
    display_name: str = Field(min_length=1, max_length=60)


class Exam(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    exam_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1, max_length=100)
    category: ExamCategoryId
    status: Literal["ACTIVE", "INACTIVE"]
    official_notice_url: HttpUrl


class ExamMenuFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categories: list[ExamCategory]
    exams: list[Exam]


class ExamMenuLoadError(ValueError):
    """Raised when the exam menu file is missing or invalid."""


def load_exam_menu(path: Path | str) -> ExamMenuFile:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        menu = ExamMenuFile.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ExamMenuLoadError(f"invalid exam menu file: {path}") from exc
    category_ids = [category.category_id for category in menu.categories]
    exam_ids = [exam.exam_id for exam in menu.exams]
    if len(category_ids) != len(set(category_ids)):
        raise ExamMenuLoadError("exam categories must be unique")
    if len(exam_ids) != len(set(exam_ids)):
        raise ExamMenuLoadError("exam ids must be unique")
    if any(exam.category not in category_ids for exam in menu.exams):
        raise ExamMenuLoadError("every exam must reference a configured category")
    return menu


def category_replies(menu: ExamMenuFile, page: int = 0) -> list[tuple[str, str]]:
    categories = menu.categories
    # Reserve one slot for navigation when another screen is available.
    start = max(0, page) * 3
    visible = categories[start : start + 3]
    replies = [
        (category.display_name, f"category:{category.category_id}")
        for category in visible
    ]
    if start + 3 < len(categories):
        replies.append(("More", "category:more"))
    elif page > 0:
        replies.append(("Back", "category:back"))
    return replies


def exam_replies(menu: ExamMenuFile, category: str) -> list[tuple[str, str]]:
    return [
        (exam.display_name, f"exam:{exam.exam_id}")
        for exam in menu.exams
        if exam.category == category and exam.status == "ACTIVE"
    ][:4]
