from __future__ import annotations

from typing import Any

from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.event_service import event_service


class TechnicalEventService:
    def _filters(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(filters or {})
        payload["bidType"] = TECHNICAL_BID_TYPE
        return payload

    async def ingest(self, user: dict[str, Any] | None, events: list[dict[str, Any]]) -> int:
        return await event_service.ingest(user, events, TECHNICAL_BID_TYPE)

    async def list(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        return await event_service.list(self._filters(filters))

    async def sessions(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        return await event_service.sessions(self._filters(filters))

    async def session_timeline(self, session_id: str) -> list[dict[str, Any]]:
        return await event_service.session_timeline(session_id, TECHNICAL_BID_TYPE)


technical_event_service = TechnicalEventService()
