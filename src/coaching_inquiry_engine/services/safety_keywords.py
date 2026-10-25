"""Load and validate configured safety keywords for the worker process."""

from __future__ import annotations

from pathlib import Path

import yaml

from coaching_inquiry_engine.domain.safety import SafetyKeywords

_KEYWORDS_PATH = Path(__file__).resolve().parents[3] / "data" / "safety_keywords.yaml"


def load_safety_keywords(path: Path | str = _KEYWORDS_PATH) -> SafetyKeywords:
    raw: object = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return SafetyKeywords.model_validate(raw)
