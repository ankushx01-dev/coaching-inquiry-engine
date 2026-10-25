"""Persist chat context and enqueue inbound message jobs.

Revision ID: 0003_chat_jobs
Revises: 0002_booking_offers
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_chat_jobs"
down_revision: str | None = "0002_booking_offers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column(
            "conversation_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_table(
        "jobs",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("inbound_message_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column(
            "attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name="fk_jobs_lead_id_leads",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["inbound_message_id"],
            ["messages.id"],
            name="fk_jobs_inbound_message_id_messages",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.UniqueConstraint(
            "inbound_message_id", name="uq_jobs_inbound_message_id"
        ),
    )
    op.create_index("ix_jobs_lead_id", "jobs", ["lead_id"])
    op.create_index(
        "ix_jobs_status_available_created",
        "jobs",
        ["status", "available_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_status_available_created", table_name="jobs")
    op.drop_index("ix_jobs_lead_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_column("leads", "conversation_context")
