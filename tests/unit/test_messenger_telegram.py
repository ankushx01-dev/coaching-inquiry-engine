"""Telegram adapter tests use an in-process HTTPX transport only."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from coaching_inquiry_engine.adapters.messenger_telegram import (
    TelegramBotApiError,
    TelegramMessenger,
)
from coaching_inquiry_engine.config import Settings
from coaching_inquiry_engine.domain.quick_replies import QuickReply


async def test_adapter_never_logs_the_bot_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = "123456:secret-token-value"

    async def reply(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    settings = Settings(
        _env_file=None,
        messenger_provider="telegram",
        telegram_bot_token=token,
        telegram_webhook_secret="webhook-secret",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        adapter = TelegramMessenger(settings=settings, client=client)
        with caplog.at_level(logging.DEBUG):
            await adapter.send_text("123", "hello")
    assert token not in caplog.text


async def test_keyboard_uses_action_id_as_callback_data() -> None:
    seen: list[bytes] = []

    async def reply(request: httpx.Request) -> httpx.Response:
        seen.append(request.content)
        return httpx.Response(200, json={"ok": True})

    settings = Settings(_env_file=None, telegram_bot_token="token")
    quick_reply = QuickReply(
        action_id="course:fees", label="Fees", send_text="Show fees"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        adapter = TelegramMessenger(settings=settings, client=client)
        await adapter.send_text("123", "Options", (quick_reply,))
    payload = json.loads(seen[0])
    button = payload["reply_markup"]["inline_keyboard"][0][0]
    assert button == {"text": "Fees", "callback_data": "course:fees"}


async def test_contact_keyboard_uses_native_contact_request() -> None:
    seen: list[bytes] = []

    async def reply(request: httpx.Request) -> httpx.Response:
        seen.append(request.content)
        return httpx.Response(200, json={"ok": True})

    settings = Settings(_env_file=None, telegram_bot_token="token")
    replies = (
        QuickReply(
            action_id="contact:shared",
            label="Share phone number",
            send_text="contact:shared",
            request_contact=True,
        ),
        QuickReply(
            action_id="contact:here",
            label="Contact me here",
            send_text="contact:here",
        ),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        adapter = TelegramMessenger(settings=settings, client=client)
        await adapter.send_text("123", "How should we contact you?", replies)
    payload = json.loads(seen[0])
    keyboard = payload["reply_markup"]
    assert keyboard["keyboard"][0] == [
        {"text": "Share phone number", "request_contact": True}
    ]
    assert keyboard["keyboard"][1] == [{"text": "Contact me here"}]


async def test_api_rejection_reports_safe_detail_without_retrying_or_logging_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = "123456:secret-token-value"
    calls = 0

    async def reject(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            401,
            json={"ok": False, "error_code": 401, "description": "Unauthorized"},
        )

    settings = Settings(
        _env_file=None,
        messenger_provider="telegram",
        telegram_bot_token=token,
        telegram_webhook_secret="webhook-secret",
        telegram_max_retries=3,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
        adapter = TelegramMessenger(settings=settings, client=client)
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(TelegramBotApiError, match="Unauthorized") as caught:
                await adapter.send_text("123", "hello")
    assert caught.value.status_code == 401
    assert calls == 1
    assert token not in str(caught.value)
    assert token not in caplog.text
    assert "(HTTP 401): Unauthorized" in caplog.text


def test_callback_data_over_64_bytes_is_rejected() -> None:
    with pytest.raises(ValueError, match="64 bytes"):
        TelegramMessenger._keyboard(
            (QuickReply(action_id="x" * 65, label="Long", send_text="Long"),)
        )


def test_telegram_provider_requires_token_and_names_setting() -> None:
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        Settings(
            _env_file=None,
            messenger_provider="telegram",
            telegram_bot_token=None,
            telegram_webhook_secret="configured-secret",
        )
