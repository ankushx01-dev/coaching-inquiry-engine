"""Email staff-alert stub; the institute must choose and configure a channel."""

from __future__ import annotations

from coaching_inquiry_engine.services.escalation_service import StaffAlertPayload


class EmailStaffAlert:
    async def send_alert(self, payload: StaffAlertPayload) -> None:
        _ = payload
        raise NotImplementedError(
            "Email delivery is a stub; the institute must choose and configure "
            "the channel"
        )
