"""Convert ORM rows to domain types. No qualification rules."""

from __future__ import annotations

from coaching_inquiry_engine.db.models import LeadRow
from coaching_inquiry_engine.domain.models import (
    ContactChannel,
    Lead,
    LeadStatus,
    Stage,
    Target,
    Timeline,
)


def lead_from_row(row: LeadRow) -> Lead:
    return Lead(
        id=row.id,
        channel=ContactChannel(row.channel),
        external_user_id=row.external_user_id,
        status=LeadStatus(row.status),
        stage=Stage(row.stage) if row.stage is not None else None,
        target=Target(row.target) if row.target is not None else None,
        timeline=Timeline(row.timeline) if row.timeline is not None else None,
        name=row.name,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
