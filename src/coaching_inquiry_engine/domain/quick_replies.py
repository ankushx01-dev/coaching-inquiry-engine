"""Quick-reply values loaded from institute-owned YAML configuration."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class QuickReply(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1, max_length=60)
    send_text: str = Field(min_length=1, max_length=1000)


class QuickReplyFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quick_replies: list[QuickReply] = Field(max_length=4)


def load_quick_replies(path: Path | str) -> list[QuickReply]:
    """Read and validate no more than four quick replies."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return QuickReplyFile.model_validate(raw).quick_replies
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ValueError(f"invalid quick replies file: {path}") from exc
