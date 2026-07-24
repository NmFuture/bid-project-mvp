from __future__ import annotations

from typing import Any

from app.services.audit_service import audit_service
from app.services.bid_type import BUSINESS_BID_TYPE
from app.services.peripheral import PeripheralError


class BusinessAuditService:
    def _filters(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(filters or {})
        payload["bidType"] = BUSINESS_BID_TYPE
        return payload

    async def list(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        return await audit_service.list(self._filters(filters))

    async def export(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        return await audit_service.export(self._filters(filters))

    async def detail(self, audit_id: str) -> dict[str, Any]:
        payload = await audit_service.detail(audit_id)
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        if str(metadata.get("bidType") or metadata.get("bid_type") or "") != BUSINESS_BID_TYPE:
            raise PeripheralError(404, "商务标审计日志不存在。", "BUSINESS_AUDIT_NOT_FOUND")
        return payload


business_audit_service = BusinessAuditService()
