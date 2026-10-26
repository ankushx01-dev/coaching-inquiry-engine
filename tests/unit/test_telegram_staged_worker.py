"""Telegram worker flow tests use fake LLM and messenger adapters."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import UUID

import httpx
import yaml

from coaching_inquiry_engine.adapters.calendar_fake import FakeCalendar
from coaching_inquiry_engine.adapters.llm_fake import FakeLlmAdapter
from coaching_inquiry_engine.adapters.messenger_fake import FakeMessenger
from coaching_inquiry_engine.agent.config import CONVERSATION_TEXTS
from coaching_inquiry_engine.agent.conversation import ConversationContext
from coaching_inquiry_engine.domain.config import BOOKING_TZ
from coaching_inquiry_engine.domain.exam_menu import load_exam_menu
from coaching_inquiry_engine.domain.flow import FlowContext, FlowStage
from coaching_inquiry_engine.domain.knowledge import load_knowledge
from coaching_inquiry_engine.domain.models import ContactChannel
from coaching_inquiry_engine.domain.sources import load_sources
from coaching_inquiry_engine.ports.llm import SanitizedMessage
from coaching_inquiry_engine.services.safety_keywords import load_safety_keywords
from coaching_inquiry_engine.worker import Worker

_NOW = datetime(2026, 10, 26, 8, 0, tzinfo=BOOKING_TZ)
_LEAD = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _worker(llm: FakeLlmAdapter, messenger: FakeMessenger) -> Worker:
    institute = load_knowledge("data/institute.yaml")
    topics = yaml.safe_load(
        Path("data/topic_keywords.yaml").read_text(encoding="utf-8")
    )
    return Worker(
        cast(object, None),
        cast(object, None),
        llm,
        messenger,
        load_safety_keywords(),
        FakeCalendar(),
        llm_max_attempts=1,
        knowledge=institute.entries,
        topic_keywords=topics,
        answering_enabled=True,
        source_registry=load_sources("data/approved_sources.yaml"),
        exam_menu=load_exam_menu("data/exams.yaml"),
        courses=institute.courses,
        qualification_options=("Class 10", "Class 12", "Graduate"),
    )


async def _send(worker: Worker, context: ConversationContext, text: str):
    return await worker.process_turn(
        lead_id=_LEAD,
        recipient="telegram-chat-id",
        inbound_text=text,
        context=context,
        prior_messages=[SanitizedMessage(role="user", text=text)],
        consent_granted=True,
        slot_options=[],
        now=_NOW,
        channel=ContactChannel.telegram,
    )


async def test_no_verified_eligibility_rule_returns_official_link() -> None:
    messenger = FakeMessenger()
    worker = _worker(FakeLlmAdapter(), messenger)
    context = ConversationContext(
        flow=FlowContext(
            stage=FlowStage.eligibility,
            exam_id="upsc_cse",
            age_years=22,
            qualification="Graduate",
        )
    )
    result = await _send(worker, context, "eligibility:check")
    assert result.context.flow.eligibility_status == "to_confirm"
    assert "https://upsc.gov.in/" in messenger.sent_texts[-1][1]
    assert result.text_keys == ["eligibility_to_confirm"]


async def test_course_pending_and_verified_fee_text() -> None:
    messenger = FakeMessenger()
    worker = _worker(FakeLlmAdapter(), messenger)
    pending = await _send(
        worker,
        ConversationContext(
            flow=FlowContext(stage=FlowStage.course_options, exam_id="jee_main")
        ),
        "course:fees",
    )
    assert pending.text_keys == ["course_info_pending"]

    verified = await _send(
        worker,
        ConversationContext(
            flow=FlowContext(stage=FlowStage.course_options, exam_id="upsc_cse")
        ),
        "course:fees",
    )
    assert "INR 60,000" in messenger.sent_texts[-1][1]
    assert verified.text_keys == []


async def test_llm_failure_uses_follow_up_without_escalating_or_handoff() -> None:
    messenger = FakeMessenger()
    worker = _worker(FakeLlmAdapter([httpx.ConnectError("offline")]), messenger)
    context = ConversationContext(
        flow=FlowContext(stage=FlowStage.course_options, exam_id="upsc_cse")
    )
    result = await _send(worker, context, "How many demo classes are available?")
    assert result.text_keys == ["llm_unavailable_follow_up"]
    assert result.status.value != "escalated"
    assert result.context.state.value != "ESCALATED"
    assert (
        CONVERSATION_TEXTS["llm_unavailable_follow_up"] in messenger.sent_texts[-1][1]
    )
    assert "Connecting you" not in messenger.sent_texts[-1][1]


async def test_category_stage_shows_only_exam_category_buttons() -> None:
    messenger = FakeMessenger()
    worker = _worker(FakeLlmAdapter(), messenger)
    context = ConversationContext(flow=FlowContext(stage=FlowStage.exam_category))
    await _send(worker, context, "category:civil_services")
    buttons = messenger.sent_quick_replies[-1]
    assert {button.action_id for button in buttons} == {
        "exam:upsc_cse",
        "exam:back",
    }


async def test_connecting_message_is_reserved_for_explicit_handoff() -> None:
    messenger = FakeMessenger()
    worker = _worker(FakeLlmAdapter(), messenger)
    context = ConversationContext(
        flow=FlowContext(stage=FlowStage.course_options, exam_id="upsc_cse")
    )
    result = await _send(worker, context, "I would like to talk to a counsellor")
    assert any("Connecting you" in text for _, text in messenger.sent_texts)
    assert result.context.state.value == "ESCALATED"


async def test_safety_trigger_escalates_without_using_human_connecting_copy() -> None:
    messenger = FakeMessenger()
    worker = _worker(FakeLlmAdapter(), messenger)
    context = ConversationContext(
        flow=FlowContext(stage=FlowStage.course_options, exam_id="upsc_cse")
    )
    result = await _send(worker, context, "I feel hopeless")
    assert result.context.state.value == "ESCALATED"
    assert "Connecting you" not in messenger.sent_texts[-1][1]
