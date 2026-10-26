"""Exam categories and labels are read from the institute-owned data file."""

from coaching_inquiry_engine.adapters.rate_limiter_memory import InMemoryRateLimiter
from coaching_inquiry_engine.domain.exam_menu import category_replies, load_exam_menu
from coaching_inquiry_engine.domain.quick_replies import load_quick_replies
from coaching_inquiry_engine.services.chat_service import ChatMessageService


def test_categories_and_exams_load_from_exams_yaml() -> None:
    menu = load_exam_menu("data/exams.yaml")

    assert {category.category_id for category in menu.categories} == {
        "engineering_medical",
        "civil_services",
        "government_banking",
        "defence_officer",
        "agnipath",
    }
    assert any(
        exam.display_name == "UPSC Civil Services Examination"
        for exam in menu.exams
    )


def test_quick_reply_category_screens_are_limited_to_four_and_no_upsc_basics() -> None:
    menu = load_exam_menu("data/exams.yaml")
    first_screen = category_replies(menu)
    second_screen = category_replies(menu, page=1)

    assert len(first_screen) <= 4
    assert len(second_screen) <= 4
    assert any(label == "More" for label, _ in first_screen)
    assert "UPSC basics" not in [label for label, _ in first_screen + second_screen]
    configured_quick_replies = load_quick_replies("data/quick_replies.yaml")
    assert "UPSC basics" not in [reply.label for reply in configured_quick_replies]


async def test_chat_quick_replies_progress_through_menu_screens() -> None:
    class Store:
        context = None

        async def conversation_context(self, _session_id: str):
            return self.context

    store = Store()
    service = ChatMessageService(
        store,
        InMemoryRateLimiter(per_session_per_minute=10, per_ip_per_minute=60),
        exam_menu=load_exam_menu("data/exams.yaml"),
    )

    categories = await service.quick_replies_for(session_id="opaque-session")
    assert len(categories) == 4
    assert categories[-1].label == "More"
    assert "UPSC basics" not in [reply.label for reply in categories]

    store.context = {"selected_category": "civil_services"}
    exams = await service.quick_replies_for(session_id="opaque-session")
    assert [reply.label for reply in exams] == [
        "UPSC Civil Services Examination",
        "Back",
    ]

    store.context = {"selected_exam": "upsc_cse"}
    actions = await service.quick_replies_for(session_id="opaque-session")
    assert {reply.label for reply in actions} == {
        "Batch timings",
        "Fees",
        "Demo class",
        "Check my eligibility",
        "Talk to a counsellor",
    }
