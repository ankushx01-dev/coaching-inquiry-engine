"""Persist fields collected by the staged Telegram flow.

Revision ID: 0005_staged_telegram_flow
Revises: 0004_outbox_dispatch
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_staged_telegram_flow"
down_revision: str | None = "0004_outbox_dispatch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("goal", sa.String(length=200), nullable=True))
    op.add_column("leads", sa.Column("age_years", sa.Integer(), nullable=True))
    op.add_column(
        "leads", sa.Column("qualification", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "leads", sa.Column("exam_category", sa.String(length=64), nullable=True)
    )
    op.add_column("leads", sa.Column("exam_id", sa.String(length=100), nullable=True))
    op.add_column(
        "leads", sa.Column("eligibility_status", sa.String(length=32), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("leads", "eligibility_status")
    op.drop_column("leads", "exam_id")
    op.drop_column("leads", "exam_category")
    op.drop_column("leads", "qualification")
    op.drop_column("leads", "age_years")
    op.drop_column("leads", "goal")
