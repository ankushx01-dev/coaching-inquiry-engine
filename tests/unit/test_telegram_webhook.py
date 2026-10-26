"""Webhook authentication and callback payload checks."""

from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from coaching_inquiry_engine.api.telegram_webhook import router


class _WebhookStub:
    async def process_update(self, update: dict[str, object]) -> bool:
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            data = callback.get("data")
            if not isinstance(data, str) or len(data.encode("utf-8")) > 64:
                raise ValueError("invalid callback")
        return True


def _app() -> FastAPI:
    app = FastAPI()
    app.state.telegram_webhook_secret = "correct-secret"
    app.state.telegram_webhook_service = _WebhookStub()
    app.include_router(router)
    return app


async def test_webhook_rejects_wrong_and_missing_secret() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        wrong = await client.post(
            "/webhooks/telegram",
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            json={"update_id": 1},
        )
        missing = await client.post("/webhooks/telegram", json={"update_id": 1})
    assert wrong.status_code == 403
    assert missing.status_code == 403


async def test_callback_data_over_64_bytes_is_rejected() -> None:
    callback_data = "x" * 65
    payload = {
        "update_id": 2,
        "callback_query": {
            "id": "callback",
            "data": callback_data,
            "message": {"chat": {"id": 10}},
        },
    }
    async with AsyncClient(
        transport=ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.post(
            "/webhooks/telegram",
            headers={"X-Telegram-Bot-Api-Secret-Token": "correct-secret"},
            json=payload,
        )
    assert response.status_code == 422
