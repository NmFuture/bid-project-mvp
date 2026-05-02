from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select

from app.models import async_session
from app.models.materials import AuditLog
from app.services.material_store import material_store
from app.services.peripheral import PeripheralError, now_day


SYSTEM_USER = {"id": "system", "name": "系统"}


def user_id_of(user: dict[str, Any] | None) -> str:
    return str((user or {}).get("id") or "system")


def user_name_of(user: dict[str, Any] | None) -> str:
    return str((user or {}).get("name") or (user or {}).get("email") or "系统")


class AuditService:
    async def _ensure_tables(self) -> None:
        async with async_session() as session:
            await material_store._ensure_runtime_tables(session)
            await session.commit()

    async def record(
        self,
        *,
        action: str,
        action_type: str,
        module_id: str,
        module_label: str,
        target: str = "",
        status: str = "成功",
        user: dict[str, Any] | None = None,
        diff: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str = "",
        user_agent: str = "",
    ) -> dict[str, Any]:
        await self._ensure_tables()
        item = AuditLog(
            user_id=user_id_of(user),
            user_name=user_name_of(user),
            action=action,
            action_type=action_type,
            module_id=module_id,
            module_label=module_label,
            target=target,
            status=status,
            diff=diff or {"before": {}, "after": {}},
            meta=metadata or {},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        async with async_session() as session:
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return item.to_dict()

    async def list(self, filters: dict[str, Any]) -> dict[str, Any]:
        await self._ensure_tables()
        async with async_session() as session:
            rows = (await session.execute(select(AuditLog).order_by(desc(AuditLog.created_at), desc(AuditLog.id)))).scalars().all()
        items = [row.to_dict() for row in rows]
        if not items:
            seed = await self.record(
                action="系统初始化",
                action_type="config",
                module_id="system",
                module_label="系统",
                target="runtime",
                user=SYSTEM_USER,
            )
            items = [seed]

        keyword = str(filters.get("keyword") or "").strip()
        user = str(filters.get("user") or "").strip()
        module = str(filters.get("module") or "").strip()
        action = str(filters.get("action") or "").strip()
        status = str(filters.get("status") or "").strip()
        start_date = str(filters.get("startDate") or "").strip()
        end_date = str(filters.get("endDate") or "").strip()

        def matched(item: dict[str, Any]) -> bool:
            if keyword and keyword not in f"{item['user']} {item['action']} {item['target']}":
                return False
            if user and item["user"] != user:
                return False
            if module and item["module"] != module:
                return False
            if action and item["actionType"] != action:
                return False
            if status and item["status"] != status:
                return False
            if start_date and str(item["time"])[:10] < start_date:
                return False
            if end_date and str(item["time"])[:10] > end_date:
                return False
            return True

        filtered = [item for item in items if matched(item)]
        modules = {(item["module"], item["moduleLabel"]) for item in items}
        actions = {(item["actionType"], item["action"]) for item in items}
        return {
            "items": filtered,
            "total": len(filtered),
            "page": 1,
            "pageSize": 20,
            "filterOptions": {
                "users": sorted({item["user"] for item in items}),
                "modules": sorted([{"id": key, "label": label} for key, label in modules], key=lambda item: item["label"]),
                "actions": sorted([{"id": key, "label": label} for key, label in actions], key=lambda item: item["label"]),
                "statuses": sorted({item["status"] for item in items}),
            },
        }

    async def detail(self, audit_id: str) -> dict[str, Any]:
        await self._ensure_tables()
        numeric_id = int(str(audit_id).replace("AUD-", ""))
        async with async_session() as session:
            row = (await session.execute(select(AuditLog).where(AuditLog.id == numeric_id))).scalar_one_or_none()
        if row is None:
            raise PeripheralError(404, "审计日志不存在。", "AUDIT_NOT_FOUND")
        payload = row.to_dict()
        payload["summary"] = f"{payload['action']} - {payload['target']}"
        return payload

    async def export(self, filters: dict[str, Any]) -> dict[str, Any]:
        data = await self.list(filters)
        return {"fileName": f"audit_{now_day()}.csv", "items": data["items"]}


audit_service = AuditService()
