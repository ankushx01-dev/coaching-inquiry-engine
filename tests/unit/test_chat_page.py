"""The embeddable chat page shows approved-pending consent and safe rendering."""

from pathlib import Path


def test_chat_page_contains_consent_notice_and_uses_text_content() -> None:
    page = Path(__file__).resolve().parents[2] / "static" / "chat.html"
    source = page.read_text(encoding="utf-8")

    assert "TO_APPROVE" in source
    assert "private AI admissions assistant for {{display_name}}" in source
    assert "[INSTITUTE_NAME]" not in source
    assert "not an official UPSC or government service" in source
    assert "Messages are stored." in source
    assert "sessionStorage" in source
    assert "crypto.getRandomValues" in source
    assert "textContent" in source
    assert "innerHTML" not in source
    assert 'id="typing-indicator"' in source
    assert 'id="quick-reply-container"' in source
    assert "quickReply.action_id" in source
    assert 'fetch("/v1/chat/messages"' in source
    assert 'fetch(`/v1/chat/messages?' in source


def test_chat_page_restores_consent_and_loads_history_on_page_load() -> None:
    page = Path(__file__).resolve().parents[2] / "static" / "chat.html"
    source = page.read_text(encoding="utf-8")

    assert 'sessionStorage.getItem("cie-chat-consent") === "true"' in source
    assert "consentPanel.hidden = true" in source
    assert "chatPanel.hidden = false" in source
    assert "startPolling();" in source
    assert "void pollMessages();" in source
