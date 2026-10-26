"""Fixed conversation keys keep review status separate from visitor text."""

from coaching_inquiry_engine.agent.config import CONVERSATION_TEXTS, TEXT_REVIEW_STATUS


def test_every_conversation_text_is_unmarked_and_has_review_status() -> None:
    assert all("TO_APPROVE" not in text for text in CONVERSATION_TEXTS.values())
    assert set(CONVERSATION_TEXTS) == set(TEXT_REVIEW_STATUS)


def test_step_09e_keys_are_unmarked_and_reviewed() -> None:
    required = {
        "course_info_pending",
        "prediction_declined",
        "eligibility_ask_age",
        "eligibility_ask_qualification",
        "eligibility_pending",
        "category_menu_intro",
        "exam_menu_intro",
    }
    assert required <= set(CONVERSATION_TEXTS)
    assert all("TO_APPROVE" not in CONVERSATION_TEXTS[key] for key in required)
    assert all(key in TEXT_REVIEW_STATUS for key in required)
