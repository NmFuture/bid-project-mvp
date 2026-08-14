"""解析链路通用件：取消检查、进度心跳、协程桥接、解析产物目录与文本归一。

来源：parsing-01 拆分，自 app/services/parsing.py 逐字搬迁，实现与行为不变；
符号经 parsing.py 门面 re-export，外部仍按 `app.services.parsing.<符号>` 访问。
"""
from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings
from app.services.bid_parse_cancel import ParseCancelledError


def _raise_if_parse_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise ParseCancelledError("解析已取消。")


def parsed_project_dir(project_id: str) -> Path:
    path = settings.parsed_dir / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def parsed_appendix_path(project_id: str) -> Path:
    return settings.parsed_dir / project_id / "s1_appendices"


def _normalize_text(raw_text: str) -> str:
    lines = [line.rstrip() for line in raw_text.replace("\r\n", "\n").split("\n")]
    compact: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line.strip()
        if blank and previous_blank:
            continue
        compact.append(line)
        previous_blank = blank
    return "\n".join(compact).strip()


def _run_with_progress_heartbeat(
    operation: Callable[[], Any],
    *,
    heartbeat: Callable[[dict[str, Any]], None],
    interval_seconds: float = 10.0,
    cancel_check: Callable[[], bool] | None = None,
) -> Any:
    result: Any = None
    error: BaseException | None = None
    done = threading.Event()

    def run() -> None:
        nonlocal result, error
        try:
            result = operation()
        except BaseException as exc:  # pragma: no cover - re-raised in caller thread
            error = exc
        finally:
            done.set()

    thread = threading.Thread(target=run, daemon=True, name="parse-progress-heartbeat")
    thread.start()
    interval = max(0.001, float(interval_seconds))
    started_at = time.monotonic()
    heartbeat_index = 0
    while not done.wait(interval):
        _raise_if_parse_cancelled(cancel_check)
        heartbeat_index += 1
        heartbeat(
            {
                "heartbeat": True,
                "heartbeatIndex": heartbeat_index,
                "elapsedSeconds": max(0, round(time.monotonic() - started_at)),
            }
        )
    thread.join()
    _raise_if_parse_cancelled(cancel_check)
    if error:
        raise error
    return result


def _run_coroutine_blocking(coro: Any) -> Any:
    """同步上下文执行协程的本模块既有桥接（OCR 识别与 opencode 引擎调用共用）。

    无线程外事件循环时直接 asyncio.run；已在事件循环里（如本地内联执行解析任务
    跑在请求线程上）则开新线程跑独立循环并 join——保持原同步阻塞语义。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: Any = None
    error: BaseException | None = None

    def run() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive bridge
            error = exc

    thread = threading.Thread(target=run, daemon=True, name="parse-blocking-bridge")
    thread.start()
    thread.join()
    if error:
        raise error
    return result
