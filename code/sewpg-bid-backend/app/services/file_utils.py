from __future__ import annotations

import asyncio
import re
import threading
from datetime import datetime
from typing import Any


def safe_filename(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


def safe_segment(value: str, fallback: str) -> str:
    return safe_filename(value, fallback)


def now_display() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def format_size_label(size: Any) -> str:
    try:
        safe_size = int(size or 0)
    except (TypeError, ValueError):
        safe_size = 0
    if safe_size < 1024:
        return f"{safe_size} B"
    if safe_size < 1024 * 1024:
        return f"{safe_size / 1024:.1f} KB"
    return f"{safe_size / 1024 / 1024:.2f} MB"


def format_size_mb(size_bytes: int) -> str:
    try:
        safe_size = int(size_bytes or 0)
    except (TypeError, ValueError):
        safe_size = 0
    if safe_size <= 0:
        return "0 MB"
    return f"{safe_size / 1024 / 1024:.1f} MB"


def run_awaitable_sync(awaitable: Any) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    loop_thread_id = getattr(loop, "_thread_id", None)
    if loop_thread_id is not None and threading.get_ident() == loop_thread_id:
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise RuntimeError(
            "run_awaitable_sync was called from the running event loop's own thread. "
            "Wrap the sync caller with asyncio.to_thread / run_in_threadpool, or use a sync route handler."
        )

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(awaitable)
        except BaseException as exc:  # pragma: no cover - re-raised in caller
            error["value"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error["value"]
    return result.get("value")
