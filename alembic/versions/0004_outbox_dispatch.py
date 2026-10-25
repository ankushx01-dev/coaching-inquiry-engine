"""Add delivery claim and failure details to the shared outbox.

Revision ID: 0004_outbox_dispatch
Revises: 0003_chat_jobs
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_outbox_dispatch"
down_revision: str | None = "0003_chat_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("outbox", sa.Column("claimed_at", sa.DateTime(timezone=True)))
    op.add_column("outbox", sa.Column("last_error", sa.Text(), nullable=True))
    op.create_index(
        "ix_outbox_status_next_attempt",
        "outbox",
        ["status", "next_attempt_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_status_next_attempt", table_name="outbox")
    op.drop_column("outbox", "last_error")
    op.drop_column("outbox", "claimed_at")
