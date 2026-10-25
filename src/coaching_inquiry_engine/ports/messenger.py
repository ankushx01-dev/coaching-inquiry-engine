"""Outbound messaging port. Adapters receive resolved, configured text only."""

from __future__ import annotations

from typing import Protocol


class MessengerPort(Protocol):
    async def send_text(self, recipient: str, text: str) -> None: ...
