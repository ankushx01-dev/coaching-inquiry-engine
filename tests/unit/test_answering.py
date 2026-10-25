"""Knowledge answering never uses the LLM for greetings or absent facts."""

from __future__ import annotations

from datetime import date

import pytest

from coaching_inquiry_engine.adapters.llm_fake import FakeLlmAdapter
from coaching_inquiry_engine.agent.answering import answer_message
from coaching_inquiry_engine.domain.config import PROMPT_VERSION
from coaching_inquiry_engine.domain.decisions import AgentDecision, NextAction
from coaching_inquiry_engine.domain.knowledge import KnowledgeEntry
from coaching_inquiry_engine.ports.llm import DecisionContext


def _knowledge() -> list[KnowledgeEntry]:
    return [
        KnowledgeEntry(
            id="fee_policy",
            topic="fees",
            text="Fee details are confirmed by the institute team.",
            source_note="Reviewed institute record",
            last_verified=date(2026, 10, 20),
            status="VERIFIED",
        )
    ]


def _decision(reply: str) -> AgentDecision:
    return AgentDecision(
        next_action=NextAction.answer_question,
        reply_text=reply,
        prompt_version=PROMPT_VERSION,
    )


def _context() -> DecisionContext:
    return DecisionContext(messages=[], allowed_next_actions=list(NextAction))


@pytest.mark.asyncio
async def test_fake_llm_answer_citing_entry_id_passes() -> None:
    llm = FakeLlmAdapter([_decision("The team confirms fee details [fee_policy].")])

    result = await answer_message(
        "What are the fees?",
        llm=llm,
        context=_context(),
        knowledge=_knowledge(),
        topic_keywords={"fees": ["fees", "fee"]},
        today=date(2026, 10, 25),
        max_attempts=1,
    )

    assert result.decision is not None
    assert result.decision.reply_text.endswith("[fee_policy].")
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_unapproved_number_is_rejected_and_retried() -> None:
    llm = FakeLlmAdapter(
        [
            _decision("Fee is 500 [fee_policy]."),
            _decision("The institute team can confirm fee details [fee_policy]."),
        ]
    )

    result = await answer_message(
        "What are the fees?",
        llm=llm,
        context=_context(),
        knowledge=_knowledge(),
        topic_keywords={"fees": ["fees", "fee"]},
        today=date(2026, 10, 25),
        max_attempts=2,
    )

    assert result.decision is not None
    assert "500" not in result.decision.reply_text
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_no_match_returns_key_without_calling_llm() -> None:
    llm = FakeLlmAdapter()

    result = await answer_message(
        "What is the campus location?",
        llm=llm,
        context=_context(),
        knowledge=_knowledge(),
        topic_keywords={"fees": ["fees", "fee"]},
        today=date(2026, 10, 25),
    )

    assert result.text_key == "knowledge_not_found"
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_greeting_returns_key_without_calling_llm() -> None:
    llm = FakeLlmAdapter()

    result = await answer_message(
        "hi 👋",
        llm=llm,
        context=_context(),
        knowledge=_knowledge(),
        topic_keywords={},
    )

    assert result.intent == "greeting"
    assert result.text_key == "greeting_welcome"
    assert llm.calls == 0
