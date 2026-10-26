"""Telegram Bot API adapter. The bot token is never included in logs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

import httpx

from coaching_inquiry_engine.config import Settings, get_settings
from coaching_inquiry_engine.domain.quick_replies import QuickReply

logger = logging.getLogger(__name__)


class TelegramBotApiError(RuntimeError):
    """Safe Telegram API failure details without the token-bearing request URL."""

    def __init__(self, status_code: int, description: str) -> None:
        self.status_code = status_code
        self.description = description
        super().__init__(f"Telegram Bot API returned {status_code}: {description}")


class _TokenRedactionFilter(logging.Filter):
    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        if self._token in rendered:
            record.msg = rendered.replace(self._token, "[REDACTED]")
            record.args = ()
        return True


class TelegramMessenger:
    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        if not self._settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        self._token = self._settings.telegram_bot_token
        for logger_name in ("httpx", "httpcore"):
            logging.getLogger(logger_name).addFilter(_TokenRedactionFilter(self._token))
        self._client = client

    async def send_text(
        self,
        recipient: str,
        text: str,
        quick_replies: tuple[QuickReply, ...] = (),
    ) -> None:
        keyboard = self._keyboard(quick_replies)
        await self._call(
            "sendMessage",
            {
                "chat_id": recipient,
                "text": text,
                **({"reply_markup": keyboard} if quick_replies else {}),
            },
        )

    async def send_consent_notice(self, recipient: str, text: str) -> None:
        await self._call(
            "sendMessage",
            {
                "chat_id": recipient,
                "text": text,
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {
                                "text": "I agree",
                                "callback_data": "consent:agree",
                            }
                        ]
                    ]
                },
            },
        )

    async def answer_callback(self, callback_query_id: str) -> None:
        await self._call(
            "answerCallbackQuery", {"callback_query_id": callback_query_id}
        )

    async def _call(self, method: str, payload: dict[str, object]) -> None:
        url = f"https://api.telegram.org/bot{self._token}/{method}"
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._settings.telegram_timeout_seconds
        )
        try:
            for attempt in range(self._settings.telegram_max_retries + 1):
                try:
                    response = await client.post(url, json=payload)
                    body = response.json()
                    if (
                        response.is_error
                        or not isinstance(body, dict)
                        or body.get("ok") is not True
                    ):
                        description = (
                            body.get("description") if isinstance(body, dict) else None
                        )
                        if not isinstance(description, str):
                            description = "unsuccessful API response"
                        description = description.replace(self._token, "[REDACTED]")[
                            :200
                        ]
                        error_status = response.status_code
                        if isinstance(body, dict) and isinstance(
                            body.get("error_code"), int
                        ):
                            error_status = body["error_code"]
                        error = TelegramBotApiError(error_status, description)
                        if 400 <= error_status < 500 and error_status != 429:
                            logger.warning(
                                "Telegram Bot API rejected the request (HTTP %d): %s",
                                error_status,
                                description,
                            )
                            raise error
                        raise error
                    return
                except TelegramBotApiError as exc:
                    if 400 <= exc.status_code < 500 and exc.status_code != 429:
                        raise
                    if attempt >= self._settings.telegram_max_retries:
                        logger.warning(
                            "Telegram Bot API request failed (HTTP %d)",
                            exc.status_code,
                        )
                        raise
                except (httpx.HTTPError, ValueError) as exc:
                    if attempt >= self._settings.telegram_max_retries:
                        logger.warning(
                            "Telegram Bot API transport failed (%s)",
                            type(exc).__name__,
                        )
                        raise RuntimeError(
                            f"Telegram Bot API transport failed ({type(exc).__name__})"
                        ) from None
                    await asyncio.sleep(
                        self._settings.telegram_retry_backoff_seconds * (2**attempt)
                    )
        finally:
            if own_client:
                await client.aclose()

    @staticmethod
    def _keyboard(replies: Sequence[QuickReply]) -> dict[str, object]:
        buttons: list[dict[str, object]] = []
        contact_buttons: list[dict[str, object]] = []
        reply_buttons: list[dict[str, object]] = []
        for reply in replies:
            if reply.request_contact:
                contact_buttons.append({"text": reply.label, "request_contact": True})
                continue
            callback = reply.action_id
            if len(callback.encode("utf-8")) > 64:
                raise ValueError("Telegram callback_data exceeds 64 bytes")
            if any(item.request_contact for item in replies):
                reply_buttons.append({"text": reply.label})
            else:
                buttons.append({"text": reply.label, "callback_data": callback})
        if contact_buttons:
            return {
                "keyboard": [contact_buttons, reply_buttons],
                "resize_keyboard": True,
                "one_time_keyboard": True,
            }
        return {"inline_keyboard": [buttons]} if buttons else {"inline_keyboard": []}
