"""Fake MessengerPort used by worker tests and local development."""

from __future__ import annotations

from coaching_inquiry_engine.domain.quick_replies import QuickReply


class FakeMessenger:
    def __init__(self) -> None:
        self.sent_texts: list[tuple[str, str]] = []
        self.sent_quick_replies: list[tuple[QuickReply, ...]] = []

    async def send_text(
        self,
        recipient: str,
        text: str,
        quick_replies: tuple[QuickReply, ...] = (),
    ) -> None:
        self.sent_texts.append((recipient, text))
        self.sent_quick_replies.append(quick_replies)
