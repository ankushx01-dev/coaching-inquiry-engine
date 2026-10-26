"""Counselling requests with one open request per lead.

Revision ID: 0006_counselling_requests
Revises: 0005_staged_telegram_flow
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_counselling_requests"
down_revision: str | None = "0005_staged_telegram_flow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "counselling_requests",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'new'"),
            nullable=False,
        ),
        sa.Column("assigned_to", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('new', 'contacted', 'booked', 'closed')",
            name=op.f("ck_counselling_requests_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name="fk_counselling_requests_lead_id_leads",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_counselling_requests"),
    )
    op.create_index(
        "uq_counselling_requests_one_open_per_lead",
        "counselling_requests",
        ["lead_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'closed'"),
        sqlite_where=sa.text("status <> 'closed'"),
    )
    op.create_index(
        "ix_counselling_requests_created_at",
        "counselling_requests",
        ["created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_counselling_requests_created_at", table_name="counselling_requests"
    )
    op.drop_index(
        "uq_counselling_requests_one_open_per_lead",
        table_name="counselling_requests",
    )
    op.drop_table("counselling_requests")
