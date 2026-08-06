from __future__ import annotations

import contextlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .checklist import shard_by_key, shard_keys
from .paths import submission_path


TARGET_KEYS = {"projectBasics", "technicalInterpretation"}
SHARDED_TARGET_KEYS = {"technicalInterpretation"}

# 分片会话是并发的独立进程，提交必须串行化，否则后写入者会覆盖先写入者的分片结果。
LOCK_TIMEOUT_SEC = 120.0
LOCK_POLL_INTERVAL_SEC = 0.05
# 持有者被强杀时锁文件会残留，超过这个年龄按陈旧锁处理，避免整条解析链路卡死。
LOCK_STALE_SEC = 300.0


def _empty() -> dict[str, Any]:
    return {
        "schemaVersion": "bid-tech-agentic-submissions-v1",
        "updatedAt": "",
        "targets": {},
        "shards": {},
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextlib.contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT_SEC
    handle: int | None = None
    while True:
        try:
            handle = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except OSError:
                age = 0.0
            if age > LOCK_STALE_SEC:
                with contextlib.suppress(OSError):
                    lock_path.unlink()
                continue
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"submission lock is busy for more than {LOCK_TIMEOUT_SEC:.0f}s: {lock_path}"
                )
            time.sleep(LOCK_POLL_INTERVAL_SEC)
    try:
        with contextlib.suppress(OSError):
            os.write(handle, str(os.getpid()).encode("utf-8"))
        yield
    finally:
        with contextlib.suppress(OSError):
            os.close(handle)
        with contextlib.suppress(OSError):
            lock_path.unlink()


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return _empty()
    # 不要吞掉解析错误：这里静默返回空会让随后的 submit 覆盖掉其它分片已提交的结果。
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return _empty()
    payload.setdefault("targets", {})
    payload.setdefault("shards", {})
    return payload


def _write(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updatedAt"] = _now()
    # 同目录临时文件 + os.replace，保证并发读取方永远看到完整 JSON。
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid4().hex[:8]}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)
    return path


def load(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    return _read(submission_path(manifest_path, manifest))


def save(manifest_path: Path, manifest: dict[str, Any], payload: dict[str, Any]) -> Path:
    path = submission_path(manifest_path, manifest)
    with _file_lock(path):
        return _write(path, payload)


def reset(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    """清空一次新编排运行前遗留的提交，避免旧结果冒充本轮产出。"""
    path = submission_path(manifest_path, manifest)
    with _file_lock(path):
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
    return path


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _row_no(row: dict[str, Any]) -> int | None:
    raw = row.get("rowNo")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    text = str(raw or "").strip()
    return int(text) if text.isdigit() else None


def _merge_shard_rows(
    existing: Any,
    incoming: Any,
    shard_key: str,
) -> tuple[list[dict[str, Any]], list[int]]:
    shard = shard_by_key(shard_key)
    allowed = set(shard["rowNos"])
    incoming_rows = _rows(incoming)
    foreign: list[int] = []
    accepted: dict[int, dict[str, Any]] = {}
    for row in incoming_rows:
        row_no = _row_no(row)
        if row_no is None or row_no not in allowed:
            foreign.append(row_no if row_no is not None else -1)
            continue
        accepted[row_no] = row
    if foreign:
        # 分片越界必须硬失败：静默丢弃会让该行永远没人负责，静默接受会覆盖别的分片。
        raise RuntimeError(
            f"shard {shard_key} submitted rowNos outside its range: {sorted(foreign)}; "
            f"allowed rowNos are {sorted(allowed)}"
        )
    merged: dict[int, dict[str, Any]] = {}
    for row in _rows(existing):
        row_no = _row_no(row)
        if row_no is None:
            continue
        merged[row_no] = row
    merged.update(accepted)
    return [merged[row_no] for row_no in sorted(merged)], sorted(accepted)


def submit(
    manifest_path: Path,
    manifest: dict[str, Any],
    target_key: str,
    value: Any,
    *,
    shard: str | None = None,
) -> dict[str, Any]:
    if target_key not in TARGET_KEYS:
        raise RuntimeError(f"unsupported targetKey: {target_key}")
    shard_key = str(shard or "").strip()
    if shard_key:
        if target_key not in SHARDED_TARGET_KEYS:
            raise RuntimeError(
                f"targetKey {target_key} does not support --shard; sharded targets are {sorted(SHARDED_TARGET_KEYS)}"
            )
        shard_by_key(shard_key)

    path = submission_path(manifest_path, manifest)
    with _file_lock(path):
        payload = _read(path)
        targets = payload.setdefault("targets", {})
        shards = payload.setdefault("shards", {})
        if shard_key:
            merged, submitted_row_nos = _merge_shard_rows(targets.get(target_key), value, shard_key)
            targets[target_key] = merged
            shards[shard_key] = {
                "targetKey": target_key,
                "rowNos": list(shard_by_key(shard_key)["rowNos"]),
                "submittedRowNos": submitted_row_nos,
                "updatedAt": _now(),
            }
            submitted_count = len(submitted_row_nos)
            total_count = len(merged)
        else:
            targets[target_key] = value
            submitted_count = len(_rows(value)) if target_key in SHARDED_TARGET_KEYS else 0
            total_count = submitted_count
        _write(path, payload)
        result = {
            "schemaVersion": "bid-tech-agentic-submit-v1",
            "status": "saved",
            "targetKey": target_key,
            "submissionPath": str(path),
            "submittedTargetCount": len(targets),
        }
        if shard_key:
            result.update(
                {
                    "shard": shard_key,
                    "shardRowCount": len(shard_by_key(shard_key)["rowNos"]),
                    "shardSubmittedRowCount": submitted_count,
                    "totalSubmittedRowCount": total_count,
                    "submittedShards": sorted(shards.keys()),
                    "pendingShards": [key for key in shard_keys() if key not in shards],
                }
            )
        return result


def shard_progress(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    payload = load(manifest_path, manifest)
    shards = payload.get("shards") if isinstance(payload.get("shards"), dict) else {}
    submitted = sorted(key for key in shards if key in set(shard_keys()))
    return {
        "shards": [
            {
                "key": key,
                "rowCount": len(shard_by_key(key)["rowNos"]),
                "submittedRowCount": len((shards.get(key) or {}).get("submittedRowNos") or []),
                "submitted": key in shards,
            }
            for key in shard_keys()
        ],
        "submittedShards": submitted,
        "pendingShards": [key for key in shard_keys() if key not in shards],
    }
