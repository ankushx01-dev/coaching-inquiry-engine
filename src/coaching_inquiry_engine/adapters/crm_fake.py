"""Idempotent fake CRM adapter for tests and local development."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID


class FakeCrm:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.contacts: dict[UUID, dict[str, str]] = {}
        self.upsert_calls: list[tuple[UUID, dict[str, str]]] = []
        self.deals: list[tuple[UUID, str]] = []

    def _maybe_fail(self) -> None:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("fake CRM temporary failure")

    async def upsert_contact(self, lead_ref: UUID, fields: Mapping[str, str]) -> None:
        self._maybe_fail()
        copied = dict(fields)
        self.upsert_calls.append((lead_ref, copied))
        self.contacts[lead_ref] = copied

    async def create_deal(self, lead_ref: UUID, stage: str) -> None:
        self._maybe_fail()
        self.deals.append((lead_ref, stage))
