"""Counselling request idempotency, uniqueness, migration, and cascade tests."""

from __future__ import annotations

import asyncio
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from coaching_inquiry_engine.db.models import CounsellingRequestRow, LeadRow
from coaching_inquiry_engine.db.repositories.counselling_requests import (
    CounsellingRequestRepository,
)
from coaching_inquiry_engine.db.repositories.leads import LeadRepository
from coaching_inquiry_engine.domain.counselling import CounsellingRequestStatus
from coaching_inquiry_engine.domain.models import ContactChannel

pytestmark = pytest.mark.integration


async def test_create_or_get_open_is_idempotent_and_closed_can_reopen(
    session: AsyncSession,
) -> None:
    lead = await LeadRepository(session, _cipher_placeholder()).get_or_create_lead(
        ContactChannel.telegram, f"counselling-{uuid4()}"
    )
    repository = CounsellingRequestRepository(session)
    first, created_first = await repository.create_or_get_open(lead.id)
    repeated, created_repeated = await repository.create_or_get_open(lead.id)
    assert created_first is True
    assert created_repeated is False
    assert first.id == repeated.id

    await repository.update(
        first.id,
        status=CounsellingRequestStatus.closed,
        assigned_to=None,
        notes=None,
        now=datetime.now(UTC),
    )
    reopened, created_again = await repository.create_or_get_open(lead.id)
    assert created_again is True
    assert reopened.id != first.id


async def test_concurrent_open_request_creation_creates_one_row(
    engine, cipher: object
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        async with session.begin():
            lead = await LeadRepository(session, cipher).get_or_create_lead(
                ContactChannel.telegram, f"concurrent-counselling-{uuid4()}"
            )
            lead_id = lead.id

    async def create_open():
        async with sessions() as session:
            async with session.begin():
                return await CounsellingRequestRepository(
                    session
                ).create_or_get_open(lead_id)

    first, second = await asyncio.gather(create_open(), create_open())
    assert first[0].id == second[0].id
    assert sum((first[1], second[1])) == 1


async def test_expiring_lead_deletes_counselling_requests(
    session: AsyncSession, cipher: object
) -> None:
    lead = await LeadRepository(session, cipher).get_or_create_lead(
        ContactChannel.telegram, f"retention-counselling-{uuid4()}"
    )
    await CounsellingRequestRepository(session).create_or_get_open(lead.id)
    row = await session.get(LeadRow, lead.id)
    assert row is not None
    row.status = "lost"
    row.updated_at = datetime.now(UTC) - timedelta(days=40)
    await session.flush()

    deleted = await LeadRepository(session, cipher).delete_expired_leads(
        datetime.now(UTC), retention_days=30
    )
    remaining = await session.scalar(
        select(func.count())
        .select_from(CounsellingRequestRow)
        .where(CounsellingRequestRow.lead_id == lead.id)
    )
    assert deleted == 1
    assert remaining == 0


async def test_migration_0006_upgrade_downgrade_and_reupgrade(engine) -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0006_counselling_requests.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0006", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = f"step09j_{uuid4().hex}"

    def run_migration(connection, function) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            function()

    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            await connection.execute(
                text("CREATE TABLE leads (id UUID PRIMARY KEY)")
            )
            await connection.run_sync(
                lambda sync_connection: run_migration(
                    sync_connection, migration.upgrade
                )
            )
            columns = await connection.run_sync(
                lambda sync_connection: {
                    item["name"]
                    for item in inspect(sync_connection).get_columns(
                        "counselling_requests"
                    )
                }
            )
            indexes = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_indexes(
                    "counselling_requests"
                )
            )
            assert {
                "id",
                "lead_id",
                "status",
                "assigned_to",
                "notes",
                "created_at",
                "updated_at",
            } <= columns
            assert any(
                item["name"] == "uq_counselling_requests_one_open_per_lead"
                and item["unique"]
                for item in indexes
            )
            await connection.run_sync(
                lambda sync_connection: run_migration(
                    sync_connection, migration.downgrade
                )
            )
            assert not await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).has_table(
                    "counselling_requests"
                )
            )
            await connection.run_sync(
                lambda sync_connection: run_migration(
                    sync_connection, migration.upgrade
                )
            )
            assert await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).has_table(
                    "counselling_requests"
                )
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def _cipher_placeholder():
    """LeadRepository only needs a configured cipher for this no-contact test."""
    from coaching_inquiry_engine.config import get_settings
    from coaching_inquiry_engine.db.encryption import ContactCipher

    return ContactCipher.from_settings(get_settings())
