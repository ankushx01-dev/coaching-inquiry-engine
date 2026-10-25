"""HubSpot CRM stub; production credentials and institute requirements are pending."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID


class HubSpotCrm:
    async def upsert_contact(self, lead_ref: UUID, fields: Mapping[str, str]) -> None:
        _ = lead_ref, fields
        raise NotImplementedError("HubSpot integration is not implemented")

    async def create_deal(self, lead_ref: UUID, stage: str) -> None:
        _ = lead_ref, stage
        raise NotImplementedError("HubSpot integration is not implemented")
