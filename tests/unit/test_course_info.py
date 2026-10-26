"""Course information is returned only from verified institute rows."""

from datetime import datetime
from typing import cast
from uuid import UUID

from coaching_inquiry_engine.adapters.calendar_fake import FakeCalendar
from coaching_inquiry_engine.adapters.llm_fake import FakeLlmAdapter
from coaching_inquiry_engine.adapters.messenger_fake import FakeMessenger
from coaching_inquiry_engine.agent.conversation import ConversationContext
from coaching_inquiry_engine.domain.config import BOOKING_TZ
from coaching_inquiry_engine.domain.exam_menu import load_exam_menu
from coaching_inquiry_engine.domain.knowledge import CourseInfoEntry, load_knowledge
from coaching_inquiry_engine.domain.safety import SafetyKeywords
from coaching_inquiry_engine.ports.llm import SanitizedMessage
from coaching_inquiry_engine.worker import Worker


async def _ask(text: str, courses=None):
    institute = load_knowledge("data/institute.yaml")
    messenger = FakeMessenger()
    keywords = SafetyKeywords.model_validate(
        {
            "review_status": "PENDING_ACADEMIC_HEAD_REVIEW",
            "categories": {
                category: {
                    "en": [category], "hi": [category], "hinglish": [category]
                }
                for category in (
                    "distress", "self_harm", "minor_signal", "scam_request",
                    "fee_dispute", "complaint", "human_request", "injection_attempt",
                )
            },
        }
    )
    worker = Worker(
        cast(object, None), cast(object, None), FakeLlmAdapter(), messenger,
        keywords, FakeCalendar(), exam_menu=load_exam_menu("data/exams.yaml"),
        courses=courses or institute.courses,
    )
    result = await worker.process_turn(
        lead_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        recipient="session", inbound_text=text,
        context=ConversationContext(selected_exam="upsc_cse"),
        prior_messages=[SanitizedMessage(role="user", text=text)],
        consent_granted=True, slot_options=[],
        now=datetime(2026, 10, 26, 8, 0, tzinfo=BOOKING_TZ),
    )
    return result, messenger


async def test_verified_batch_dates_are_returned_from_institute_yaml() -> None:
    result, messenger = await _ask("course:batch_timings")
    assert result.text_keys == []
    assert messenger.sent_texts == [
        (
            "session",
            "Batch start dates: 1 Nov 2026 and 1 Jan 2027; timings not provided.",
        )
    ]


def test_course_data_includes_unverified_fees_dates_and_demo_configuration() -> None:
    institute = load_knowledge("data/institute.yaml")

    assert set(institute.courses) == {
        "upsc_cse",
        "jee_main",
        "neet_ug",
        "ssc_cgl",
        "ibps_po",
        "cds",
        "nda",
        "agnipath",
    }
    assert institute.courses["upsc_cse"]["fees"].status == "VERIFIED"
    for course in institute.courses.values():
        assert course["batch_timings"].status == "VERIFIED"
        assert "1 Nov 2026" in course["batch_timings"].text
        assert "1 Jan 2027" in course["batch_timings"].text
        assert course["demo_class"].status == "VERIFIED"
        assert course["demo_class"].available is True
        assert course["demo_class"].mode is None
        assert course["demo_class"].schedule is None
    for exam_id, course in institute.courses.items():
        if exam_id != "upsc_cse":
            assert course["fees"].status == "TO_VERIFY"


async def test_verified_batch_timing_is_returned_from_configured_course_entry() -> None:
    result, messenger = await _ask(
        "What are the batch timings?",
        courses={
            "upsc_cse": {
                "batch_timings": CourseInfoEntry(
                    text="Morning and evening batches are available.",
                    status="VERIFIED",
                )
            }
        },
    )
    assert result.text_keys == []
    assert messenger.sent_texts == [
        ("session", "Morning and evening batches are available.")
    ]
