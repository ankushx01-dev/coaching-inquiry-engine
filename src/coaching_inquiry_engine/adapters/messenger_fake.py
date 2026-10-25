"""Fake MessengerPort used by worker tests and local development."""

from __future__ import annotations


class FakeMessenger:
    def __init__(self) -> None:
        self.sent_texts: list[tuple[str, str]] = []

    async def send_text(self, recipient: str, text: str) -> None:
        self.sent_texts.append((recipient, text))
