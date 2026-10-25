"""Fixed conversation keys keep review status separate from visitor text."""

from coaching_inquiry_engine.agent.config import CONVERSATION_TEXTS, TEXT_REVIEW_STATUS


def test_every_conversation_text_is_unmarked_and_has_review_status() -> None:
    assert all("TO_APPROVE" not in text for text in CONVERSATION_TEXTS.values())
    assert set(CONVERSATION_TEXTS) == set(TEXT_REVIEW_STATUS)
