from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import patch

from app.services import bid_parse_service


class ParseEventLoopSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_tender_parse_runs_in_worker_thread_without_blocking_event_loop(self) -> None:
        timeline: list[str] = []

        def slow_parse(*_args, **_kwargs):
            time.sleep(0.05)
            timeline.append("parse-finished")
            return (
                {"fileCount": 1, "extractedCount": 1, "textLength": 1, "textPreview": "", "warnings": []},
                {"documents": [], "items": [], "structured": {}, "projectUpdates": {}},
            )

        async def heartbeat() -> None:
            await asyncio.sleep(0.01)
            timeline.append("event-loop-alive")

        with patch("app.services.bid_parse_service.parse_tender_documents", side_effect=slow_parse):
            await asyncio.gather(
                bid_parse_service._parse_tender_documents_async(
                    "PRJ-LOOP",
                    [],
                    bid_type="商务标",
                    progress_callback=None,
                ),
                heartbeat(),
            )

        self.assertEqual(timeline[0], "event-loop-alive")
