"""Standalone process loop for shared CRM and staff-alert outbox delivery."""

from __future__ import annotations

import asyncio

from coaching_inquiry_engine.adapters.clock import SystemClock
from coaching_inquiry_engine.adapters.crm_fake import FakeCrm
from coaching_inquiry_engine.adapters.crm_hubspot import HubSpotCrm
from coaching_inquiry_engine.adapters.staff_alert_email import EmailStaffAlert
from coaching_inquiry_engine.adapters.staff_alert_telegram import TelegramStaffAlert
from coaching_inquiry_engine.config import get_settings
from coaching_inquiry_engine.db.repositories.outbox import OutboxRepository
from coaching_inquiry_engine.db.session import create_engine, create_session_factory
from coaching_inquiry_engine.services.outbox_service import drain_outbox


async def run_outbox_worker() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    clock = SystemClock()
    crm = FakeCrm() if settings.crm_provider == "fake" else HubSpotCrm()
    staff_alerts = (
        EmailStaffAlert()
        if settings.staff_alert_channel == "email"
        else TelegramStaffAlert()
    )
    repository = OutboxRepository(sessions)
    try:
        while True:
            count = await drain_outbox(
                clock.now(),
                crm,
                staff_alerts,
                settings.outbox_batch_size,
                repository=repository,
                clock=clock,
                max_attempts=settings.job_max_attempts,
                base_backoff_seconds=settings.outbox_base_backoff_seconds,
            )
            if count == 0:
                await asyncio.sleep(0.5)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_outbox_worker())
