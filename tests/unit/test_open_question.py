"""Direct answers to an outstanding qualifying question are parsed first."""

from datetime import datetime
from typing import cast
from uuid import UUID

from coaching_inquiry_engine.adapters.calendar_fake import FakeCalendar
from coaching_inquiry_engine.adapters.llm_fake import FakeLlmAdapter
from coaching_inquiry_engine.adapters.messenger_fake import FakeMessenger
from coaching_inquiry_engine.agent.conversation import ConversationContext, Field
from coaching_inquiry_engine.domain.config import BOOKING_TZ
from coaching_inquiry_engine.domain.models import LeadProfile, Stage, Target
from coaching_inquiry_engine.domain.safety import SafetyKeywords
from coaching_inquiry_engine.ports.llm import SanitizedMessage
from coaching_inquiry_engine.worker import Worker


def _worker() -> tuple[Worker, FakeLlmAdapter]:
    llm = FakeLlmAdapter()
    categories = (
        "distress", "self_harm", "minor_signal", "scam_request", "fee_dispute",
        "complaint", "human_request", "injection_attempt",
    )
    keywords = SafetyKeywords.model_validate(
        {
            "review_status": "PENDING_ACADEMIC_HEAD_REVIEW",
            "categories": {
                name: {"en": [name], "hi": [name], "hinglish": [name]}
                for name in categories
            },
        }
    )
    return Worker(
        cast(object, None), cast(object, None), llm, FakeMessenger(), keywords,
        FakeCalendar(),
    ), llm


async def _reply(worker: Worker, context: ConversationContext, text: str):
    return await worker.process_turn(
        lead_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        recipient="session", inbound_text=text, context=context,
        prior_messages=[SanitizedMessage(role="user", text=text)],
        consent_granted=True, slot_options=[],
        now=datetime(2026, 10, 26, 8, 0, tzinfo=BOOKING_TZ),
    )


async def test_name_reply_is_stored_and_next_qualifying_question_is_asked() -> None:
    worker, llm = _worker()
    context = ConversationContext(
        profile=LeadProfile(stage=Stage.first_attempt),
        last_asked_field=Field.target,
    )
    result = await _reply(worker, context, "my name is Ankush")

    assert result.context.name == "Ankush"
    assert result.text_keys == ["ask_target"]
    assert llm.calls == 0


async def test_stage_reply_is_stored_and_target_is_asked_next() -> None:
    worker, llm = _worker()
    result = await _reply(
        worker, ConversationContext(last_asked_field=Field.stage), "first attempt"
    )

    assert result.context.profile.stage is Stage.first_attempt
    assert result.text_keys == ["ask_target"]
    assert llm.calls == 0


async def test_target_reply_is_stored_and_timeline_is_asked_next() -> None:
    worker, llm = _worker()
    result = await _reply(
        worker,
        ConversationContext(
            profile=LeadProfile(stage=Stage.first_attempt),
            last_asked_field=Field.target,
        ),
        "prelims",
    )

    assert result.context.profile.target is Target.prelims
    assert result.text_keys == ["ask_timeline"]
    assert llm.calls == 0
