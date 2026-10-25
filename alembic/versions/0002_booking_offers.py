"""Add slot offer option_index and active-offer uniqueness.

Revision ID: 0002_booking_offers
Revises: 0001_initial
Create Date: 2026-10-25

expires_at and used already exist on slot_offers from 0001_initial.
This revision adds option_index and a partial unique index so one lead
cannot hold two unused offers with the same index.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_booking_offers"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "slot_offers",
        sa.Column(
            "option_index",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "uq_slot_offers_active_lead_option",
        "slot_offers",
        ["lead_id", "option_index"],
        unique=True,
        postgresql_where=sa.text("used = false"),
    )
    op.alter_column("slot_offers", "option_index", server_default=None)


def downgrade() -> None:
    op.drop_index(
        "uq_slot_offers_active_lead_option",
        table_name="slot_offers",
        postgresql_where=sa.text("used = false"),
    )
    op.drop_column("slot_offers", "option_index")
