from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.materials import UserEventLog
from app.services.bid_type import BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE
from app.services.event_service import EventService, MAX_META_BYTES


CREATE_TABLE_SQL = """
CREATE TABLE user_event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR(100) NOT NULL,
    user_name VARCHAR(100),
    session_id VARCHAR(100) NOT NULL,
    bid_type VARCHAR(20) NOT NULL,
    event_type VARCHAR(20) NOT NULL,
    route VARCHAR(500),
    element VARCHAR(200),
    target VARCHAR(500),
    status VARCHAR(20),
    duration_ms INT,
    trace_id VARCHAR(100),
    meta JSONB,
    client_ts TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
)
"""


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


class EventServiceTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.execute(text(CREATE_TABLE_SQL))
        self.service = EventService()
        patches = (
            patch("app.services.event_service.async_session", self.session_factory),
            patch("app.services.event_service.ensure_material_runtime_tables", new=AsyncMock()),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _insert(self, **kwargs: Any) -> UserEventLog:
        row = UserEventLog(
            user_id=kwargs.get("user_id", "u-1"),
            user_name=kwargs.get("user_name", "张三"),
            session_id=kwargs.get("session_id", "sess-1"),
            bid_type=kwargs.get("bid_type", TECHNICAL_BID_TYPE),
            event_type=kwargs.get("event_type", "click"),
            route=kwargs.get("route"),
            element=kwargs.get("element"),
            target=kwargs.get("target"),
            status=kwargs.get("status"),
            duration_ms=kwargs.get("duration_ms"),
            trace_id=kwargs.get("trace_id"),
            meta=kwargs.get("meta", {}),
            client_ts=kwargs.get("client_ts"),
            created_at=kwargs.get("created_at", _ts("2026-07-20 10:00:00")),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row


class IngestTests(EventServiceTestCase):
    async def test_ingest_stamps_server_fields_and_filters_invalid_events(self) -> None:
        user = {"id": "u-9", "name": "李四"}
        events = [
            {"sessionId": "sess-a", "eventType": "click", "route": "/workspace/tech", "clientTs": "2026-07-20T09:00:00Z"},
            {"sessionId": "sess-a", "eventType": "hover"},  # 非法 eventType，丢弃
            {"sessionId": "", "eventType": "click"},  # 缺 sessionId，丢弃
            {"sessionId": "sess-a", "eventType": "error", "status": "error", "clientTs": "not-a-date"},
            "not-a-dict",
        ]
        accepted = await self.service.ingest(user, events, TECHNICAL_BID_TYPE)
        self.assertEqual(accepted, 2)

        data = await self.service.list({"bidType": TECHNICAL_BID_TYPE, "pageSize": 10})
        self.assertEqual(data["total"], 2)
        items = {item["eventType"]: item for item in data["items"]}
        click = items["click"]
        self.assertTrue(click["id"].startswith("EVT-"))
        self.assertEqual(click["userId"], "u-9")
        self.assertEqual(click["userName"], "李四")
        self.assertEqual(click["bidType"], TECHNICAL_BID_TYPE)
        self.assertTrue(click["clientTs"])
        # clientTs 解析失败时置空，由服务端 created_at 兜底
        self.assertEqual(items["error"]["clientTs"], "")
        self.assertTrue(items["error"]["createdAt"])

    async def test_ingest_truncates_oversized_meta(self) -> None:
        meta = {"payload": "x" * (MAX_META_BYTES * 2)}
        accepted = await self.service.ingest(
            {"id": "u-1"},
            [{"sessionId": "sess-m", "eventType": "api", "meta": meta}],
            TECHNICAL_BID_TYPE,
        )
        self.assertEqual(accepted, 1)
        data = await self.service.list({"bidType": TECHNICAL_BID_TYPE})
        stored = data["items"][0]["meta"]
        self.assertTrue(stored["truncated"])
        self.assertLessEqual(len(stored["preview"]), MAX_META_BYTES)

    async def test_ingest_returns_zero_when_nothing_valid(self) -> None:
        accepted = await self.service.ingest(None, [{"eventType": "bad"}], TECHNICAL_BID_TYPE)
        self.assertEqual(accepted, 0)
        data = await self.service.list({"bidType": TECHNICAL_BID_TYPE})
        self.assertEqual(data["total"], 0)


class ListTests(EventServiceTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self._insert(
            session_id="sess-1", event_type="click", route="/workspace/tech/home",
            element="提交按钮", target="tech-submit", user_id="u-1", user_name="张三",
            created_at=_ts("2026-07-18 08:00:00"),
        )
        await self._insert(
            session_id="sess-1", event_type="api", route="/api/technical/generate",
            target="generate", status="success", user_id="u-1", user_name="张三",
            created_at=_ts("2026-07-19 09:00:00"),
        )
        await self._insert(
            session_id="sess-2", event_type="error", route="/workspace/tech/gap",
            element="缺口面板", target="gap-panel", status="error", user_id="u-2", user_name="王五",
            created_at=_ts("2026-07-20 10:00:00"),
        )
        await self._insert(
            session_id="sess-3", event_type="route", route="/workspace/business/home",
            user_id="u-3", user_name="赵六", bid_type=BUSINESS_BID_TYPE,
            created_at=_ts("2026-07-21 11:00:00"),
        )

    async def test_list_filters_by_event_type_user_route_and_keyword(self) -> None:
        by_type = await self.service.list({"eventType": "click"})
        self.assertEqual(by_type["total"], 1)
        self.assertEqual(by_type["items"][0]["element"], "提交按钮")

        by_user_name = await self.service.list({"user": "张三"})
        self.assertEqual(by_user_name["total"], 2)
        by_user_id = await self.service.list({"user": "u-2"})
        self.assertEqual(by_user_id["total"], 1)

        by_route = await self.service.list({"route": "/workspace/tech"})
        self.assertEqual(by_route["total"], 2)
        by_route_api = await self.service.list({"route": "/api/technical"})
        self.assertEqual(by_route_api["total"], 1)

        by_keyword = await self.service.list({"keyword": "缺口"})
        self.assertEqual(by_keyword["total"], 1)
        by_keyword_en = await self.service.list({"keyword": "GENERATE"})
        self.assertEqual(by_keyword_en["total"], 1)

        by_session = await self.service.list({"sessionId": "sess-1"})
        self.assertEqual(by_session["total"], 2)

    async def test_list_filters_by_date_range_and_bid_type(self) -> None:
        ranged = await self.service.list({"startDate": "2026-07-19", "endDate": "2026-07-20"})
        self.assertEqual(ranged["total"], 2)

        technical = await self.service.list({"bidType": TECHNICAL_BID_TYPE})
        self.assertEqual(technical["total"], 3)
        business = await self.service.list({"bidType": BUSINESS_BID_TYPE})
        self.assertEqual(business["total"], 1)

    async def test_list_paginates_and_orders_by_created_at_desc(self) -> None:
        page1 = await self.service.list({"page": 1, "pageSize": 2})
        self.assertEqual(page1["total"], 4)
        self.assertEqual(page1["page"], 1)
        self.assertEqual(page1["pageSize"], 2)
        self.assertEqual(len(page1["items"]), 2)
        self.assertEqual(page1["items"][0]["route"], "/workspace/business/home")

        page2 = await self.service.list({"page": 2, "pageSize": 2})
        self.assertEqual(len(page2["items"]), 2)
        self.assertEqual(page2["items"][-1]["route"], "/workspace/tech/home")

        # pageSize 上限 100，默认值 20
        capped = await self.service.list({"pageSize": 500})
        self.assertEqual(capped["pageSize"], 100)
        defaulted = await self.service.list({})
        self.assertEqual(defaulted["pageSize"], 20)


class SessionsTests(EventServiceTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        base = dict(user_id="u-1", user_name="张三")
        await self._insert(**base, session_id="sess-a", event_type="click", client_ts=_ts("2026-07-20 09:00:00"))
        await self._insert(**base, session_id="sess-a", event_type="error", status="error", client_ts=_ts("2026-07-20 09:05:00"))
        await self._insert(**base, session_id="sess-a", event_type="api", status="error", client_ts=_ts("2026-07-20 09:10:00"))
        await self._insert(
            user_id="u-2", user_name="王五", session_id="sess-b", event_type="click",
            client_ts=_ts("2026-07-21 10:00:00"), created_at=_ts("2026-07-21 10:00:00"),
        )
        await self._insert(
            user_id="u-3", user_name="赵六", session_id="sess-c", event_type="click",
            bid_type=BUSINESS_BID_TYPE, client_ts=_ts("2026-07-22 10:00:00"),
            created_at=_ts("2026-07-22 10:00:00"),
        )

    async def test_sessions_aggregates_and_orders_by_end_ts_desc(self) -> None:
        data = await self.service.sessions({})
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["items"][0]["sessionId"], "sess-c")

        tech = await self.service.sessions({"bidType": TECHNICAL_BID_TYPE})
        self.assertEqual(tech["total"], 2)
        first, second = tech["items"][0], tech["items"][1]
        self.assertEqual(first["sessionId"], "sess-b")
        self.assertEqual(second["sessionId"], "sess-a")
        self.assertEqual(second["userId"], "u-1")
        self.assertEqual(second["userName"], "张三")
        self.assertEqual(second["eventCount"], 3)
        self.assertEqual(second["errorCount"], 2)  # eventType=error 与 status=error 各算一次去重后的条数
        self.assertEqual(second["startTs"][:19], "2026-07-20T09:00:00")
        self.assertEqual(second["endTs"][:19], "2026-07-20T09:10:00")

    async def test_sessions_filters_by_user_date_and_paginates(self) -> None:
        by_user = await self.service.sessions({"user": "张三"})
        self.assertEqual(by_user["total"], 1)
        self.assertEqual(by_user["items"][0]["sessionId"], "sess-a")

        by_date = await self.service.sessions({"startDate": "2026-07-21", "endDate": "2026-07-21"})
        self.assertEqual(by_date["total"], 1)
        self.assertEqual(by_date["items"][0]["sessionId"], "sess-b")

        page = await self.service.sessions({"page": 2, "pageSize": 2})
        self.assertEqual(page["total"], 3)
        self.assertEqual(len(page["items"]), 1)


class TimelineTests(EventServiceTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self._insert(session_id="sess-t", event_type="api", target="third", client_ts=_ts("2026-07-20 09:10:00"))
        await self._insert(session_id="sess-t", event_type="click", target="first", client_ts=_ts("2026-07-20 09:00:00"))
        # client_ts 为空时回退 created_at 排序
        await self._insert(session_id="sess-t", event_type="route", target="second", client_ts=None, created_at=_ts("2026-07-20 09:05:00"))
        await self._insert(
            session_id="sess-t", event_type="click", target="other-line",
            bid_type=BUSINESS_BID_TYPE, client_ts=_ts("2026-07-20 09:01:00"),
        )

    async def test_timeline_orders_by_client_ts_with_created_at_fallback(self) -> None:
        items = await self.service.session_timeline("sess-t", TECHNICAL_BID_TYPE)
        self.assertEqual([item["target"] for item in items], ["first", "second", "third"])

    async def test_timeline_is_isolated_by_bid_type(self) -> None:
        business_items = await self.service.session_timeline("sess-t", BUSINESS_BID_TYPE)
        self.assertEqual([item["target"] for item in business_items], ["other-line"])


if __name__ == "__main__":
    unittest.main()
