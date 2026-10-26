"""Telegram webhook authentication and update validation."""

from __future__ import annotations

import secrets
from typing import Annotated, cast

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from coaching_inquiry_engine.services.telegram_webhook import TelegramWebhookService

router = APIRouter(tags=["telegram"])


class TelegramUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    update_id: int


@router.post("/webhooks/telegram", status_code=200)
async def telegram_webhook(
    payload: TelegramUpdate,
    request: Request,
    secret: Annotated[
        str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")
    ] = None,
) -> dict[str, bool]:
    expected = request.app.state.telegram_webhook_secret
    if not isinstance(secret, str) or not secrets.compare_digest(
        secret.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    service = cast(
        TelegramWebhookService | None, request.app.state.telegram_webhook_service
    )
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    try:
        await service.process_update(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    return {"ok": True}
