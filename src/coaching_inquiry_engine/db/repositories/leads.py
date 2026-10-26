"""Lead aggregate persistence. Identity, contact protection, and retention."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from coaching_inquiry_engine.db.encryption import ContactCipher
from coaching_inquiry_engine.db.mapping import lead_from_row
from coaching_inquiry_engine.db.models import LeadRow
from coaching_inquiry_engine.domain.models import (
    Contact,
    ContactChannel,
    Lead,
    LeadProfile,
    LeadStatus,
)


class LeadRepository:
    def __init__(self, session: AsyncSession, cipher: ContactCipher) -> None:
        self._session = session
        self._cipher = cipher

    async def get_or_create_lead(
        self, channel: ContactChannel, external_user_id: str
    ) -> Lead:
        stmt = (
            insert(LeadRow)
            .values(
                channel=channel.value,
                external_user_id=external_user_id,
                status=LeadStatus.nurture.value,
            )
            .on_conflict_do_nothing(constraint="uq_leads_channel_external_user_id")
        )
        await self._session.execute(stmt)
        row = await self._session.scalar(
            select(LeadRow).where(
                LeadRow.channel == channel.value,
                LeadRow.external_user_id == external_user_id,
            )
        )
        if row is None:
            raise RuntimeError("lead row missing after get_or_create")
        return lead_from_row(row)

    async def get_by_id(self, lead_id: UUID) -> Lead | None:
        row = await self._session.get(LeadRow, lead_id)
        return lead_from_row(row) if row is not None else None

    async def get_by_channel_external_user(
        self, channel: ContactChannel, external_user_id: str
    ) -> Lead | None:
        row = await self._session.scalar(
            select(LeadRow).where(
                LeadRow.channel == channel.value,
                LeadRow.external_user_id == external_user_id,
            )
        )
        return lead_from_row(row) if row is not None else None

    async def get_conversation_context(self, lead_id: UUID) -> dict[str, object] | None:
        row = await self._session.get(LeadRow, lead_id)
        if row is None:
            raise KeyError(f"lead {lead_id} not found")
        return deepcopy(row.conversation_context)

    async def get_decrypted_contact_value(self, lead_id: UUID) -> str | None:
        row = await self._session.get(LeadRow, lead_id)
        if row is None:
            raise KeyError(f"lead {lead_id} not found")
        if row.contact_encrypted is None:
            return None
        return self._cipher.decrypt(row.contact_encrypted)

    async def save_conversation_context(
        self,
        lead_id: UUID,
        context: dict[str, object],
        profile: LeadProfile,
        status: LeadStatus,
    ) -> None:
        row = await self._session.get(LeadRow, lead_id)
        if row is None:
            raise KeyError(f"lead {lead_id} not found")

        stored_context = deepcopy(context)
        profile_data = stored_context.get("profile")
        if isinstance(profile_data, dict):
            contact_data = profile_data.get("contact")
            if isinstance(contact_data, dict):
                contact_data["value"] = "[ENCRYPTED]"

        flow_data = stored_context.get("flow")
        if isinstance(flow_data, dict):
            flow_name = flow_data.get("name")
            row.name = flow_name if isinstance(flow_name, str) else row.name
            goal = flow_data.get("goal")
            row.goal = goal if isinstance(goal, str) else None
            age = flow_data.get("age_years")
            row.age_years = age if isinstance(age, int) else None
            qualification = flow_data.get("qualification")
            row.qualification = (
                qualification if isinstance(qualification, str) else None
            )
            category = flow_data.get("exam_category")
            row.exam_category = category if isinstance(category, str) else None
            exam_id = flow_data.get("exam_id")
            row.exam_id = exam_id if isinstance(exam_id, str) else None
            eligibility = flow_data.get("eligibility_status")
            row.eligibility_status = (
                eligibility if isinstance(eligibility, str) else None
            )

        if profile.contact is not None:
            row.name = profile.contact.name
            row.contact_encrypted = self._cipher.encrypt(profile.contact.value)
            row.contact_hash = self._cipher.hash_contact(profile.contact.value)
        row.status = status.value
        row.stage = profile.stage.value if profile.stage is not None else None
        row.target = profile.target.value if profile.target is not None else None
        row.timeline = profile.timeline.value if profile.timeline is not None else None
        row.conversation_context = stored_context
        await self._session.flush()

    async def set_contact(self, lead_id: UUID, contact: Contact) -> Lead:
        row = await self._session.get(LeadRow, lead_id)
        if row is None:
            raise KeyError(f"lead {lead_id} not found")
        row.name = contact.name
        row.contact_encrypted = self._cipher.encrypt(contact.value)
        row.contact_hash = self._cipher.hash_contact(contact.value)
        await self._session.flush()
        await self._session.refresh(row, attribute_names=["updated_at"])
        return lead_from_row(row)

    async def delete_expired_leads(self, now: datetime, retention_days: int) -> int:
        cutoff = now - timedelta(days=retention_days)
        result = await self._session.execute(
            delete(LeadRow).where(
                LeadRow.status == LeadStatus.lost.value,
                LeadRow.updated_at < cutoff,
            )
        )
        return result.rowcount or 0
