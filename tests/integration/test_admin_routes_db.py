"""Staff request dashboard projections and audit behavior on PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from coaching_inquiry_engine.api.admin_routes import router
from coaching_inquiry_engine.config import Settings
from coaching_inquiry_engine.db.encryption import ContactCipher
from coaching_inquiry_engine.db.models import (
    AuditEventRow,
    CounsellingRequestRow,
    LeadRow,
)
from coaching_inquiry_engine.db.repositories.consents import ConsentRepository
from coaching_inquiry_engine.db.repositories.counselling_requests import (
    CounsellingRequestRepository,
)
from coaching_inquiry_engine.db.repositories.leads import LeadRepository
from coaching_inquiry_engine.db.repositories.messages import MessageRepository
from coaching_inquiry_engine.domain.exam_menu import load_exam_menu
from coaching_inquiry_engine.domain.models import (
    Contact,
    ContactChannel,
    MessageDirection,
)
from coaching_inquiry_engine.services.admin_auth import (
    AdminAuthRateLimiter,
    hash_admin_password,
)

pytestmark = pytest.mark.integration


class _DecryptSpy:
    def __init__(self, cipher: ContactCipher) -> None:
        self.cipher = cipher
        self.decrypt_calls = 0

    def decrypt(self, value: bytes) -> str:
        self.decrypt_calls += 1
        return self.cipher.decrypt(value)


def _admin_app(engine: AsyncEngine, spy: _DecryptSpy) -> FastAPI:
    application = FastAPI()
    application.state.settings = Settings(
        _env_file=None,
        admin_enabled=True,
        admin_username="staff-user",
        admin_password_hash=hash_admin_password("secret", iterations=100_000),
    )
    application.state.admin_auth_limiter = AdminAuthRateLimiter()
    application.state.exam_menu = load_exam_menu("data/exams.yaml")
    application.state.admin_sessions = async_sessionmaker(
        engine, expire_on_commit=False
    )
    application.state.contact_cipher = spy
    application.include_router(router)
    return application


async def test_list_is_contact_free_and_detail_status_audit_are_escaped(
    engine: AsyncEngine, cipher: ContactCipher
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        async with session.begin():
            lead = await LeadRepository(session, cipher).get_or_create_lead(
                ContactChannel.telegram, f"admin-dashboard-{uuid4()}"
            )
            await LeadRepository(session, cipher).set_contact(
                lead.id,
                Contact(
                    name="Asha Sharma",
                    channel=ContactChannel.call,
                    value="9876543210",
                ),
            )
            lead_row = await session.get(LeadRow, lead.id)
            assert lead_row is not None
            lead_row.name = "<script>alert(1)</script>"
            lead_row.age_years = 22
            lead_row.qualification = "Graduate"
            lead_row.exam_id = "upsc_cse"
            lead_row.eligibility_status = "eligible"
            lead_row.goal = "Civil services"
            request_row, created = await CounsellingRequestRepository(
                session
            ).create_or_get_open(lead.id)
            assert created
            await ConsentRepository(session).record_consent(
                lead.id, ContactChannel.telegram, "telegram-v1"
            )
            for index in range(6):
                await MessageRepository(session).insert_message_if_new(
                    f"admin-message-{uuid4()}",
                    lead.id,
                    MessageDirection.inbound,
                    f"history {index}: +919876543210 or asha@example.com",
                    datetime.now(UTC) + timedelta(seconds=index),
                )
            request_id = request_row.id

    spy = _DecryptSpy(cipher)
    app = _admin_app(engine, spy)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        listing = await client.get(
            "/admin/requests?exam=upsc_cse&status=new", auth=("staff-user", "secret")
        )
        assert listing.status_code == 200
        assert "9876543210" not in listing.text
        assert "asha@example.com" not in listing.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in listing.text
        assert spy.decrypt_calls == 0

        detail = await client.get(
            f"/admin/requests/{request_id}", auth=("staff-user", "secret")
        )
        assert detail.status_code == 200
        assert "+919876543210" in detail.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in detail.text
        assert "<script>alert(1)</script>" not in detail.text
        assert "[REDACTED]" in detail.text
        assert "history 0" not in detail.text
        assert "history 5" in detail.text
        assert spy.decrypt_calls == 1

        updated = await client.post(
            f"/admin/requests/{request_id}/status",
            auth=("staff-user", "secret"),
            json={
                "status": "contacted",
                "assigned_to": "agent-1",
                "notes": "<b>Reviewed</b>",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["status"] == "contacted"
        assert "9876543210" not in updated.text

        detail_after_update = await client.get(
            f"/admin/requests/{request_id}", auth=("staff-user", "secret")
        )
        assert "&lt;b&gt;Reviewed&lt;/b&gt;" in detail_after_update.text
        filtered = await client.get(
            "/admin/requests?exam=upsc_cse&status=contacted",
            auth=("staff-user", "secret"),
        )
        assert filtered.status_code == 200
        assert "1 request(s)" in filtered.text

    async with sessions() as session:
        events = list(
            await session.scalars(
                select(AuditEventRow)
                .where(AuditEventRow.lead_id == lead.id)
                .order_by(AuditEventRow.created_at)
            )
        )
        assert len(events) == 3
        assert {event.event_type for event in events} == {
            "admin_contact_detail_viewed",
            "admin_counselling_request_status_changed",
        }
        assert all("9876543210" not in str(event.detail) for event in events)
        assert all("asha@example.com" not in str(event.detail) for event in events)
        stored = await session.get(CounsellingRequestRow, request_id)
        assert stored is not None and stored.status == "contacted"


async def test_request_list_paginates_at_25_and_orders_newest_first(
    engine: AsyncEngine, cipher: ContactCipher
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    created_requests: list[CounsellingRequestRow] = []
    request_ids = []
    async with sessions() as session:
        async with session.begin():
            for index in range(26):
                lead = await LeadRepository(session, cipher).get_or_create_lead(
                    ContactChannel.telegram, f"admin-page-{uuid4()}"
                )
                lead_row = await session.get(LeadRow, lead.id)
                assert lead_row is not None
                lead_row.exam_id = "upsc_cse"
                request_row = CounsellingRequestRow(
                    lead_id=lead.id,
                    status="new",
                    created_at=now.replace(microsecond=index),
                    updated_at=now,
                )
                session.add(request_row)
                created_requests.append(request_row)
            await session.flush()
            request_ids = [
                row.id
                for row in sorted(
                    created_requests,
                    key=lambda item: item.created_at,
                    reverse=True,
                )
            ]

    app = _admin_app(engine, _DecryptSpy(cipher))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.get(
            "/admin/requests?page=1", auth=("staff-user", "secret")
        )
        second = await client.get(
            "/admin/requests?page=2", auth=("staff-user", "secret")
        )
    assert first.status_code == second.status_code == 200
    assert first.text.count("href=\"/admin/requests/") == 25
    assert second.text.count("href=\"/admin/requests/") == 1
    assert "26 request(s)" in first.text
    assert first.text.index(f"/admin/requests/{request_ids[0]}") < first.text.index(
        f"/admin/requests/{request_ids[-2]}"
    )
    assert f"/admin/requests/{request_ids[-1]}" in second.text


async def test_request_list_applies_inclusive_date_range(
    engine: AsyncEngine, cipher: ContactCipher
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    target_day = datetime(2026, 5, 17, 12, tzinfo=UTC)
    async with sessions() as session:
        async with session.begin():
            for created_at in (
                target_day - timedelta(days=1),
                target_day,
                target_day + timedelta(days=1),
            ):
                lead = await LeadRepository(session, cipher).get_or_create_lead(
                    ContactChannel.telegram, f"admin-date-{uuid4()}"
                )
                session.add(
                    CounsellingRequestRow(
                        lead_id=lead.id,
                        status="new",
                        created_at=created_at,
                        updated_at=target_day,
                    )
                )

    app = _admin_app(engine, _DecryptSpy(cipher))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/admin/requests?date_from=2026-05-17&date_to=2026-05-17",
            auth=("staff-user", "secret"),
        )
    assert response.status_code == 200
    assert "1 request(s)" in response.text
