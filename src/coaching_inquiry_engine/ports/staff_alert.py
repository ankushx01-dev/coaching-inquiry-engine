"""Staff alert delivery port."""

from __future__ import annotations

from typing import Protocol

from coaching_inquiry_engine.services.escalation_service import StaffAlertPayload


class StaffAlertPort(Protocol):
    async def send_alert(self, payload: StaffAlertPayload) -> None: ...
