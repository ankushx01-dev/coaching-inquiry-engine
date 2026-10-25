"""Route-level tests for the embeddable chat page response headers."""

from types import SimpleNamespace

from httpx import ASGITransport, AsyncClient

from coaching_inquiry_engine.api import chat_page
from coaching_inquiry_engine.config import get_settings
from coaching_inquiry_engine.main import app


async def test_chat_page_returns_consent_and_configured_embed_policy(
    monkeypatch,
) -> None:
    settings = get_settings()
    origin = settings.chat_allowed_origin
    monkeypatch.setattr(chat_page, "get_settings", lambda: settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        response = await client.get("/chat")

    assert response.status_code == 200
    policy = response.headers["content-security-policy"]
    assert f"frame-ancestors 'self' {origin}" in policy
    assert "x-frame-options" not in response.headers
    assert "TO_APPROVE" in response.text
    assert "private AI admissions assistant for [INSTITUTE_NAME]" in response.text


async def test_chat_page_uses_self_only_when_origin_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        chat_page,
        "get_settings",
        lambda: SimpleNamespace(chat_allowed_origin=""),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        response = await client.get("/chat")

    assert response.status_code == 200
    policy = response.headers["content-security-policy"]
    assert policy == "frame-ancestors 'self'"
    assert "  " not in policy
    assert "x-frame-options" not in response.headers
