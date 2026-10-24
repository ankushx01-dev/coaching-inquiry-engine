"""AgentDecision schema: parse, extra=forbid, booking index rules."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from coaching_inquiry_engine.domain import AgentDecision, NextAction

_SRC = Path(__file__).resolve().parents[2] / "src" / "coaching_inquiry_engine"
_FORBIDDEN = frozenset({"httpx", "ollama", "openai", "anthropic", "langchain"})

_VALID = {
    "next_action": "ask_field",
    "reply_text": "Which stage of preparation are you in?",
    "field_updates": {},
    "booking_choice_index": None,
    "escalation_reason": None,
    "prompt_version": "upsc_v0.2",
}


def test_valid_json_parses() -> None:
    decision = AgentDecision.model_validate_json(json.dumps(_VALID))
    assert decision.next_action is NextAction.ask_field
    assert decision.booking_choice_index is None


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentDecision.model_validate({**_VALID, "temperature": 0})


def test_booking_choice_index_five_with_three_offers_rejected() -> None:
    payload = {
        **_VALID,
        "next_action": "booking_choice",
        "booking_choice_index": 5,
        "reply_text": "Taking the last listed slot.",
    }
    with pytest.raises(ValidationError):
        AgentDecision.model_validate(payload)


def test_index_with_non_booking_action_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentDecision.model_validate({**_VALID, "booking_choice_index": 1})


def test_domain_and_agent_have_no_vendor_llm_imports() -> None:
    imported: set[str] = set()
    for path in (_SRC / "domain").rglob("*.py"):
        _collect_imports(path, imported)
    for path in (_SRC / "agent").rglob("*.py"):
        _collect_imports(path, imported)
    assert imported.isdisjoint(_FORBIDDEN)


def _collect_imports(path: Path, imported: set[str]) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module.split(".")[0])
