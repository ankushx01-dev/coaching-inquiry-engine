"""Outbound messaging port. Adapters receive resolved, configured text only."""

from __future__ import annotations

from typing import Protocol

from coaching_inquiry_engine.domain.quick_replies import QuickReply


class MessengerPort(Protocol):
    async def send_text(
        self,
        recipient: str,
        text: str,
        quick_replies: tuple[QuickReply, ...] = (),
    ) -> None: ...
