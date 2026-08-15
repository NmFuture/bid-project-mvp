from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.bid_runtime_state import now_iso


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


def run_local_skill_runner(
    runner: Path,
    manifest_path: Path,
    schema_version: str,
    *,
    error_label: str = "Skill runner",
    schema_key: str = "schema_version",
    model_id: str | None = None,
    payload_text_fallback: bool = False,
) -> dict[str, Any]:
    """本地 skill runner 子进程执行的共享实现（技术标/商务标缺口链路同源）。

    - error_label/schema_key：商务标链路用中文标签和 camelCase 的 schemaVersion。
    - model_id：默认取 runner 所在 skill 目录名（runner.parent.parent.name）；
      商务标链路固定写 skill 名常量。
    - payload_text_fallback：stdout 为空时 opencodeOutput 正文回退为 payload JSON
      （商务标链路行为；技术标链路 runner 必打印摘要，不会走到）。
    """
    if not runner.exists():
        raise RuntimeError(f"{error_label} 不存在：{runner}")
    result = subprocess.run(
        [sys.executable, str(runner), "--manifest", str(manifest_path), "--response", "summary"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        detail = "\n".join(part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part)
        raise RuntimeError(f"{error_label} 执行失败（{result.returncode}）：{detail}")
    payload = json.loads(result.stdout or "{}")
    payload.setdefault(schema_key, schema_version)
    text = result.stdout.strip()
    if not text and payload_text_fallback:
        text = json.dumps(payload, ensure_ascii=False)
    payload.setdefault(
        "opencodeOutput",
        {
            "status": "received",
            "sessionId": str(manifest_path),
            "providerId": "local-skill",
            "modelId": model_id or runner.parent.parent.name,
            "receivedAt": now_iso(),
            "parts": [{"type": "text", "text": text}],
        },
    )
    return payload
