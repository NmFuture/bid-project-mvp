from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import case, desc, func, or_, select

from app.models import async_session
from app.models.materials import UserEventLog
from app.services.audit_service import user_id_of, user_name_of
from app.services.material_runtime_tables import ensure_material_runtime_tables


EVENT_TYPES = {"click", "route", "api", "error"}
MAX_META_BYTES = 4096
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _paging(filters: dict[str, Any]) -> tuple[int, int]:
    try:
        page = max(1, int(filters.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(filters.get("pageSize") or DEFAULT_PAGE_SIZE)
    except (TypeError, ValueError):
        page_size = DEFAULT_PAGE_SIZE
    page_size = min(max(1, page_size), MAX_PAGE_SIZE)
    return page, page_size


def _parse_client_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _parse_duration_ms(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _truncate_meta(value: Any) -> dict[str, Any]:
    meta = dict(value) if isinstance(value, dict) else {}
    text = json.dumps(meta, ensure_ascii=False)
    if len(text.encode("utf-8")) <= MAX_META_BYTES:
        return meta
    return {"truncated": True, "preview": text[:MAX_META_BYTES]}


class EventService:
    async def _ensure_tables(self) -> None:
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            await session.commit()

    def _user_date_conditions(self, filters: dict[str, Any]) -> list[Any]:
        conditions: list[Any] = []
        bid_type = str(filters.get("bidType") or "").strip()
        user = str(filters.get("user") or "").strip()
        start_date = str(filters.get("startDate") or "").strip()
        end_date = str(filters.get("endDate") or "").strip()
        if bid_type:
            conditions.append(UserEventLog.bid_type == bid_type)
        if user:
            conditions.append(or_(UserEventLog.user_name == user, UserEventLog.user_id == user))
        if start_date:
            conditions.append(func.date(UserEventLog.created_at) >= start_date)
        if end_date:
            conditions.append(func.date(UserEventLog.created_at) <= end_date)
        return conditions

    async def ingest(self, user: dict[str, Any] | None, events: list[dict[str, Any]], bid_type: str) -> int:
        await self._ensure_tables()
        rows: list[UserEventLog] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("eventType") or "").strip()
            if event_type not in EVENT_TYPES:
                continue
            session_id = str(event.get("sessionId") or "").strip()
            if not session_id:
                continue
            rows.append(
                UserEventLog(
                    user_id=user_id_of(user),
                    user_name=user_name_of(user),
                    session_id=session_id,
                    bid_type=bid_type,
                    event_type=event_type,
                    route=str(event.get("route") or "") or None,
                    element=str(event.get("element") or "") or None,
                    target=str(event.get("target") or "") or None,
                    status=str(event.get("status") or "") or None,
                    duration_ms=_parse_duration_ms(event.get("durationMs")),
                    trace_id=str(event.get("traceId") or "") or None,
                    meta=_truncate_meta(event.get("meta")),
                    client_ts=_parse_client_ts(event.get("clientTs")),
                )
            )
        if not rows:
            return 0
        async with async_session() as session:
            session.add_all(rows)
            await session.commit()
        return len(rows)

    async def list(self, filters: dict[str, Any]) -> dict[str, Any]:
        await self._ensure_tables()
        conditions = self._user_date_conditions(filters)
        event_type = str(filters.get("eventType") or "").strip()
        session_id = str(filters.get("sessionId") or "").strip()
        route = str(filters.get("route") or "").strip()
        keyword = str(filters.get("keyword") or "").strip()
        if event_type:
            conditions.append(UserEventLog.event_type == event_type)
        if session_id:
            conditions.append(UserEventLog.session_id == session_id)
        if route:
            conditions.append(UserEventLog.route.like(f"{route}%"))
        if keyword:
            pattern = f"%{keyword}%"
            conditions.append(
                or_(
                    UserEventLog.element.ilike(pattern),
                    UserEventLog.target.ilike(pattern),
                    UserEventLog.route.ilike(pattern),
                )
            )
        page, page_size = _paging(filters)
        async with async_session() as session:
            total = (
                await session.execute(select(func.count()).select_from(UserEventLog).where(*conditions))
            ).scalar_one()
            rows = (
                await session.execute(
                    select(UserEventLog)
                    .where(*conditions)
                    .order_by(desc(UserEventLog.created_at), desc(UserEventLog.id))
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).scalars().all()
        return {
            "items": [row.to_dict() for row in rows],
            "total": total,
            "page": page,
            "pageSize": page_size,
        }

    async def sessions(self, filters: dict[str, Any]) -> dict[str, Any]:
        await self._ensure_tables()
        conditions = self._user_date_conditions(filters)
        page, page_size = _paging(filters)
        error_count = func.sum(
            case(
                (or_(UserEventLog.status == "error", UserEventLog.event_type == "error"), 1),
                else_=0,
            )
        ).label("error_count")
        async with async_session() as session:
            total = (
                await session.execute(
                    select(func.count(func.distinct(UserEventLog.session_id))).where(*conditions)
                )
            ).scalar_one()
            rows = (
                await session.execute(
                    select(
                        UserEventLog.session_id.label("session_id"),
                        func.min(UserEventLog.user_id).label("user_id"),
                        func.max(UserEventLog.user_name).label("user_name"),
                        func.min(UserEventLog.client_ts).label("start_ts"),
                        func.max(UserEventLog.client_ts).label("end_ts"),
                        func.count().label("event_count"),
                        error_count,
                    )
                    .where(*conditions)
                    .group_by(UserEventLog.session_id)
                    .order_by(desc("end_ts"), desc("session_id"))
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        items = [
            {
                "sessionId": row.session_id,
                "userId": row.user_id or "",
                "userName": row.user_name or "",
                "startTs": row.start_ts.isoformat() if row.start_ts else "",
                "endTs": row.end_ts.isoformat() if row.end_ts else "",
                "eventCount": row.event_count,
                "errorCount": row.error_count or 0,
            }
            for row in rows
        ]
        return {"items": items, "total": total, "page": page, "pageSize": page_size}

    async def session_timeline(self, session_id: str, bid_type: str) -> list[dict[str, Any]]:
        await self._ensure_tables()
        conditions = [UserEventLog.session_id == session_id]
        if bid_type:
            conditions.append(UserEventLog.bid_type == bid_type)
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(UserEventLog)
                    .where(*conditions)
                    .order_by(func.coalesce(UserEventLog.client_ts, UserEventLog.created_at), UserEventLog.id)
                )
            ).scalars().all()
        return [row.to_dict() for row in rows]


event_service = EventService()
