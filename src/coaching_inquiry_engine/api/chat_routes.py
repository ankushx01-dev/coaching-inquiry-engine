"""HTTP routes for asynchronous chat intake and reply retrieval."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from coaching_inquiry_engine.domain.models import MessageDirection
from coaching_inquiry_engine.domain.quick_replies import QuickReply
from coaching_inquiry_engine.services.chat_service import (
    ChatMessageService,
    RateLimitExceededError,
)

_SESSION_TOKEN = r"^[A-Za-z0-9_-]{32,128}$"


class ChatMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=32, max_length=128, pattern=_SESSION_TOKEN)
    client_message_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=1000)
    consent_given: bool


class AcceptedMessageResponse(BaseModel):
    accepted: bool
    message_id: UUID


class ChatMessageResponse(BaseModel):
    message_id: UUID
    direction: MessageDirection
    text: str
    received_at: datetime


class ChatRepliesResponse(BaseModel):
    messages: list[ChatMessageResponse]
    quick_replies: list[QuickReply]


def get_chat_service(request: Request) -> ChatMessageService:
    return cast(ChatMessageService, request.app.state.chat_message_service)


router = APIRouter(prefix="/v1/chat/messages", tags=["chat"])


@router.post("", response_model=AcceptedMessageResponse, status_code=202)
async def post_chat_message(
    payload: ChatMessageRequest,
    request: Request,
    service: Annotated[ChatMessageService, Depends(get_chat_service)],
) -> AcceptedMessageResponse:
    ip_address = request.client.host if request.client is not None else "unknown"
    try:
        accepted = await service.submit(
            session_id=payload.session_id,
            client_message_id=payload.client_message_id,
            text=payload.text,
            consent_given=payload.consent_given,
            ip_address=ip_address,
        )
    except RateLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS) from exc
    return AcceptedMessageResponse(
        accepted=accepted.accepted,
        message_id=accepted.message_id,
    )


@router.get("", response_model=ChatRepliesResponse)
async def get_chat_replies(
    service: Annotated[ChatMessageService, Depends(get_chat_service)],
    session_id: str = Query(
        min_length=32,
        max_length=128,
        pattern=_SESSION_TOKEN,
    ),
) -> ChatRepliesResponse:
    messages = await service.messages(session_id=session_id)
    return ChatRepliesResponse(
        messages=[
            ChatMessageResponse(
                message_id=message.message_id,
                direction=message.direction,
                text=message.text,
                received_at=message.received_at,
            )
            for message in messages
        ],
        quick_replies=list(service.quick_replies),
    )
