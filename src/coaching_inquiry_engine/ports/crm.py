"""CRM synchronization port."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol
from uuid import UUID


class CrmPort(Protocol):
    async def upsert_contact(
        self, lead_ref: UUID, fields: Mapping[str, str]
    ) -> None: ...

    async def create_deal(self, lead_ref: UUID, stage: str) -> None: ...
