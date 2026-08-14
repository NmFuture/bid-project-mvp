from __future__ import annotations

import copy
from typing import Any

from app.services.bid_runtime_state import build_directory_event, now_iso

# 「重新生成索引」单独占一个顶层字段，不并进 fill_state：
# fill_state 的 status/percentage/tasks 有「拼装正文三步」的固定语义，
# 共用会让共创导出页的正文轮询把索引任务误当成正文重新生成。
SCORE_INDEX_STATE_FIELD = "score_index_state"

_MAX_EVENTS = 20


def default_score_index_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "percentage": 0,
        "startedAt": "",
        "finishedAt": "",
        "cancelRequested": False,
        "cancelRequestedAt": "",
        "cancelledAt": "",
        "runDurationSec": 0,
        "summary": "尚未单独重新生成章节索引。",
        "indexProgress": None,
        "output": None,
        "warnings": [],
        "error": "",
        "events": [],
    }


def score_index_state(project: dict[str, Any]) -> dict[str, Any]:
    current = project.get(SCORE_INDEX_STATE_FIELD)
    if not isinstance(current, dict):
        return default_score_index_state()
    return copy.deepcopy(current)


def start_score_index_state(project: dict[str, Any]) -> dict[str, Any]:
    started_at = now_iso()
    summary = "已开始重新生成章节索引，正在定位技术评分标准索引表。"
    payload = {
        **default_score_index_state(),
        "status": "running",
        "percentage": 3,
        "startedAt": started_at,
        "summary": summary,
        "events": [build_directory_event(summary, step="bootstrap", at=started_at)],
    }
    project[SCORE_INDEX_STATE_FIELD] = payload
    project["updatedAt"] = started_at
    return copy.deepcopy(payload)


def update_score_index_state(
    project: dict[str, Any],
    *,
    percentage: int | None = None,
    summary: str | None = None,
    status: str | None = None,
    index_progress: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    error: str | None = None,
    event_message: str | None = None,
    event_level: str = "info",
    event_step: str = "general",
) -> dict[str, Any]:
    current = score_index_state(project)
    if percentage is not None:
        clamped = max(0, min(100, int(percentage)))
        # 运行中只增不减：阶段回调乱序到达时不让进度条倒退。
        if status in (None, "running"):
            clamped = max(clamped, int(current.get("percentage") or 0))
        current["percentage"] = clamped
    if index_progress is not None:
        done = max(0, int(index_progress.get("done") or 0))
        total = max(0, int(index_progress.get("total") or 0))
        previous = current.get("indexProgress") if isinstance(current.get("indexProgress"), dict) else {}
        if total > 0:
            done = min(done, total)
            # 计数同样单调：体检算出的「已有索引行数」不该被后续阶段的中间值抹低。
            done = max(done, min(int(previous.get("done") or 0), total))
        current["indexProgress"] = {
            "done": done,
            "total": total,
            "phase": str(index_progress.get("phase") or ""),
            # updatedAt 同时充当心跳，供卡死判定使用。
            "updatedAt": now_iso(),
        }
    if summary is not None:
        current["summary"] = summary
    if status is not None:
        current["status"] = status
    if output is not None:
        current["output"] = copy.deepcopy(output)
    if warnings is not None:
        current["warnings"] = copy.deepcopy(warnings)
    if error is not None:
        current["error"] = error
    if event_message:
        events = list(current.get("events") or [])
        events.append(build_directory_event(event_message, level=event_level, step=event_step))
        current["events"] = events[-_MAX_EVENTS:]
    project[SCORE_INDEX_STATE_FIELD] = current
    project["updatedAt"] = now_iso()
    return copy.deepcopy(current)


def finish_score_index_state(
    project: dict[str, Any],
    *,
    status: str,
    summary: str,
    run_duration_sec: int,
    output: dict[str, Any] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    error: str = "",
    event_step: str = "done",
    event_level: str = "success",
) -> dict[str, Any]:
    current = score_index_state(project)
    finished_at = now_iso()
    current["status"] = status
    current["percentage"] = 100 if status == "completed" else int(current.get("percentage") or 0)
    current["finishedAt"] = finished_at
    current["runDurationSec"] = max(0, int(run_duration_sec))
    current["summary"] = summary
    current["output"] = copy.deepcopy(output) if output is not None else current.get("output")
    current["warnings"] = copy.deepcopy(warnings or [])
    current["error"] = error
    events = list(current.get("events") or [])
    events.append(build_directory_event(summary, level=event_level, step=event_step, at=finished_at))
    current["events"] = events[-_MAX_EVENTS:]
    project[SCORE_INDEX_STATE_FIELD] = current
    project["updatedAt"] = finished_at
    return copy.deepcopy(current)
