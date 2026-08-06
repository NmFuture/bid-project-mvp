"""Regression tests for the production hang on sync-to-async material helpers.

The bug: the sync bridge runs an awaitable from sync code by
spawning a worker thread that runs its own event loop, then ``thread.join``s
to wait for the result. If the *calling* thread is already an event loop's
own thread (which is what happens when an ``async def`` FastAPI handler
calls into a sync helper), the join blocks the event loop and the
entire FastAPI process stops responding (including ``/healthz``).

These tests pin two invariants so the bug can't silently come back:

1. ``_run_async`` raises a clear ``RuntimeError`` if invoked from a thread
   that owns a running event loop, instead of silently freezing.
2. The route handlers that fan into ``_run_async`` are declared as plain
   ``def`` (not ``async def``), so FastAPI runs them in a worker thread
   and they never end up calling sync->async->thread.join from the loop's
   own thread.
"""

from __future__ import annotations

import asyncio
import inspect
import unittest

from app.api.routes import technical as technical_routes
from app.services.file_utils import run_awaitable_sync


class RunAsyncEventLoopGuardTests(unittest.TestCase):
    def test_run_async_rejects_call_from_running_event_loop_thread(self) -> None:
        """If someone calls ``_run_async`` while standing on the event loop's
        own thread, freezing the server is the worst possible outcome — make
        the bug visible by raising at call time instead."""

        async def inner_coro() -> int:
            return 42

        async def caller() -> None:
            with self.assertRaises(RuntimeError) as ctx:
                run_awaitable_sync(inner_coro())
            self.assertIn("event loop", str(ctx.exception).lower())

        asyncio.run(caller())

    def test_run_async_works_from_plain_sync_context(self) -> None:
        """The non-loop case still works (``asyncio.run`` path)."""

        async def inner_coro() -> str:
            return "ok"

        result = run_awaitable_sync(inner_coro())
        self.assertEqual(result, "ok")


class GapHeavySyncRouteHandlersAreNotAsyncTests(unittest.TestCase):
    """The technical ``/api/technical/projects/.../gaps[-detection]?/...`` endpoints whose
    sync-to-async bridge MUST be ``def``
    handlers, not ``async def``. FastAPI then dispatches them via
    ``run_in_threadpool`` and the thread-blocking ``thread.join`` inside
    ``_run_async`` no longer freezes the event loop."""

    EXPECTED_SYNC_HANDLERS = [
        "run_technical_gap_detection",
        "ai_fill_all_technical_gap_materials",
        "ai_fill_technical_gap_material",
        "upload_technical_gap_material",
        # 一键正文填写只做提交（收集目标 + 入队），但落库链路与上面同源，保持同一纪律
        "body_fill_technical_gaps",
    ]

    def test_handlers_are_plain_def_not_async_def(self) -> None:
        for name in self.EXPECTED_SYNC_HANDLERS:
            handler = getattr(technical_routes, name, None)
            self.assertIsNotNone(handler, f"handler {name} not found in technical routes")
            self.assertFalse(
                inspect.iscoroutinefunction(handler),
                msg=(
                    f"{name} is async def — calling it on the FastAPI event loop "
                    f"would deadlock when the chain reaches run_awaitable_sync. "
                    f"Change it to plain 'def' so FastAPI runs it in a worker thread."
                ),
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
