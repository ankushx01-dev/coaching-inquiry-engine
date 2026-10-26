"""Eligibility responses use only verified, exam-specific approved sources."""

from datetime import datetime
from typing import cast
from uuid import UUID

from coaching_inquiry_engine.adapters.calendar_fake import FakeCalendar
from coaching_inquiry_engine.adapters.llm_fake import FakeLlmAdapter
from coaching_inquiry_engine.adapters.messenger_fake import FakeMessenger
from coaching_inquiry_engine.agent.config import CONVERSATION_TEXTS
from coaching_inquiry_engine.agent.conversation import ConversationContext
from coaching_inquiry_engine.domain.config import BOOKING_TZ
from coaching_inquiry_engine.domain.exam_menu import load_exam_menu
from coaching_inquiry_engine.domain.knowledge import load_knowledge
from coaching_inquiry_engine.domain.safety import SafetyKeywords
from coaching_inquiry_engine.domain.sources import SourceEntry
from coaching_inquiry_engine.ports.llm import SanitizedMessage
from coaching_inquiry_engine.worker import Worker

_NOW = datetime(2026, 10, 26, 8, 0, tzinfo=BOOKING_TZ)
_KEYWORDS = SafetyKeywords.model_validate(
    {
        "review_status": "PENDING_ACADEMIC_HEAD_REVIEW",
        "categories": {
            category: {
                "en": [f"trigger {category}"],
                "hi": [f"हिंदी {category}"],
                "hinglish": [f"hinglish {category}"],
            }
            for category in (
                "distress", "self_harm", "minor_signal", "scam_request",
                "fee_dispute", "complaint", "human_request", "injection_attempt",
            )
        },
    }
)


def _worker(messenger: FakeMessenger, source_registry=None) -> Worker:
    institute = load_knowledge("data/institute.yaml")
    return Worker(
        cast(object, None), cast(object, None), FakeLlmAdapter(), messenger,
        _KEYWORDS, FakeCalendar(), exam_menu=load_exam_menu("data/exams.yaml"),
        courses=institute.courses, source_registry=source_registry or {},
    )


async def _send(worker: Worker, text: str, context: ConversationContext):
    return await worker.process_turn(
        lead_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        recipient="session", inbound_text=text,
        context=context,
        prior_messages=[SanitizedMessage(role="user", text=text)],
        consent_granted=True, slot_options=[], now=_NOW,
    )


async def _eligibility(worker: Worker) -> object:
    context = ConversationContext(selected_exam="upsc_cse")
    start = await _send(worker, "Check my eligibility", context)
    age = await _send(
        worker, "22-25", start.context
    )
    return await _send(worker, "Graduate", age.context)


async def test_no_verified_entry_returns_pending_key_with_official_link() -> None:
    messenger = FakeMessenger()
    result = await _eligibility(_worker(messenger))

    assert result.text_keys == ["eligibility_pending"]
    assert CONVERSATION_TEXTS["eligibility_pending"].format(
        official_url="https://upsc.gov.in/"
    ) in [text for _, text in messenger.sent_texts]
    assert result.context.age_band == "22-25"
    assert result.context.qualification_band == "Graduate"
    assert result.context.age_band not in result.context.profile.model_dump().values()


async def test_verified_exam_entry_is_used_without_computing_eligibility() -> None:
    source = SourceEntry(
        id="cse-eligibility",
        topic="eligibility",
        official_url="https://upsc.gov.in/",
        answer_summary="Read the exam notice for the stated requirements.",
        last_verified=_NOW.date(),
        owner="upsc",
        status="VERIFIED",
        exam_id="upsc_cse",
    )
    messenger = FakeMessenger()
    result = await _eligibility(_worker(messenger, {"upsc_cse:eligibility": source}))

    assert result.text_keys == []
    assert any("stated requirements" in text for _, text in messenger.sent_texts)
    assert any("https://upsc.gov.in/" in text for _, text in messenger.sent_texts)


def test_eligibility_never_asks_for_date_of_birth() -> None:
    assert "date of birth" not in CONVERSATION_TEXTS["eligibility_ask_age"].casefold()
    assert "date of birth" not in CONVERSATION_TEXTS[
        "eligibility_ask_qualification"
    ].casefold()
