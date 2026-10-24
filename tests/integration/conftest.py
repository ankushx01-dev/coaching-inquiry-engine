"""PostgreSQL 16 fixtures for persistence tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from coaching_inquiry_engine.config import get_settings
from coaching_inquiry_engine.db.base import Base
from coaching_inquiry_engine.db.encryption import ContactCipher
from coaching_inquiry_engine.db.models import (  # noqa: F401
    AuditEventRow,
    BookingRow,
    ConsentRow,
    LeadRow,
    MessageRow,
    OutboxRow,
    SlotOfferRow,
)

_TRUNCATE = """
TRUNCATE TABLE
    audit_events, outbox, bookings, slot_offers, consents, messages, leads
CASCADE
"""


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine, expire_on_commit=False
    )
    async with factory() as session:
        await session.execute(text(_TRUNCATE))
        await session.commit()
        yield session
        await session.rollback()


@pytest.fixture
def cipher() -> ContactCipher:
    return ContactCipher.from_settings(get_settings())
