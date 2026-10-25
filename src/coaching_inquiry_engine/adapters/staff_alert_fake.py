"""Fake staff alert adapter for tests."""

from __future__ import annotations

from coaching_inquiry_engine.services.escalation_service import StaffAlertPayload


class FakeStaffAlert:
    def __init__(self) -> None:
        self.alerts: list[StaffAlertPayload] = []

    async def send_alert(self, payload: StaffAlertPayload) -> None:
        self.alerts.append(payload)
