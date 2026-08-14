"""技术标解析附表写入项目素材库的后台任务。"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from app.services.background_job_registry import is_job_active, start_job
from app.services.technical_parse_assets import (
    persist_technical_parse_result,
    sync_technical_parse_appendices,
)
from app.services.workspace_project_access import (
    persist_workspace_project_fields,
    require_any_workspace_project_for_update,
)

TECHNICAL_PARSE_ASSET_SYNC_JOB_PREFIX = "technical-parse-asset-sync"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _selected_count(project: dict[str, Any]) -> int:
    parse_result = project.get("parse_result") if isinstance(project.get("parse_result"), dict) else {}
    structured = parse_result.get("structured") if isinstance(parse_result.get("structured"), dict) else {}
    appendices = structured.get("appendices") if isinstance(structured.get("appendices"), list) else []
    return sum(
        1
        for item in appendices
        if isinstance(item, dict) and item.get("selectedForMaterial") is True
    )


def parse_asset_sync_state(project: dict[str, Any]) -> dict[str, Any]:
    state = project.get("technicalParseAssetSyncState")
    return copy.deepcopy(state) if isinstance(state, dict) else {"status": "idle"}


def _write_state(project_id: str, **fields: Any) -> dict[str, Any]:
    project = require_any_workspace_project_for_update(
        project_id,
        not_found_error=lambda pid: KeyError(pid),
    )
    state = parse_asset_sync_state(project)
    state.update(fields)
    project["technicalParseAssetSyncState"] = state
    persist_workspace_project_fields(project, "technicalParseAssetSyncState")
    return copy.deepcopy(state)


def recover_stale_technical_parse_asset_sync(project_id: str) -> dict[str, Any]:
    project = require_any_workspace_project_for_update(
        project_id,
        not_found_error=lambda pid: KeyError(pid),
    )
    state = parse_asset_sync_state(project)
    job_name = f"{TECHNICAL_PARSE_ASSET_SYNC_JOB_PREFIX}:{project_id}"
    if str(state.get("status") or "") != "running" or is_job_active(job_name):
        return state
    return _write_state(
        project_id,
        status="failed",
        message="后台同步任务已中断，可点击重试。",
        error="后台服务重启或任务被取消，解析附表尚未完成同步。",
        finishedAt=_now_iso(),
    )


def schedule_technical_parse_asset_sync(project_id: str) -> dict[str, Any]:
    project = require_any_workspace_project_for_update(
        project_id,
        not_found_error=lambda pid: KeyError(pid),
    )
    selected_count = _selected_count(project)
    state = _write_state(
        project_id,
        status="running",
        selectedCount=selected_count,
        syncedCount=0,
        uploadedCount=0,
        deletedCount=0,
        message=f"正在同步 {selected_count} 个解析附表到项目素材库。",
        error="",
        startedAt=_now_iso(),
        finishedAt="",
    )

    async def run() -> dict[str, Any]:
        latest_project = require_any_workspace_project_for_update(
            project_id,
            not_found_error=lambda pid: KeyError(pid),
        )
        parse_result = copy.deepcopy(
            latest_project.get("parse_result")
            if isinstance(latest_project.get("parse_result"), dict)
            else {}
        )
        result: dict[str, Any] = {}
        error: Exception | None = None
        try:
            result = await sync_technical_parse_appendices(latest_project, parse_result)
        except Exception as exc:  # noqa: BLE001 - 原始失败原因需要写回项目状态
            error = exc

        try:
            persist_technical_parse_result(project_id, parse_result)
        except Exception as exc:  # noqa: BLE001 - 清单断点保存失败同样属于任务失败
            if error is None:
                error = exc

        if error is not None:
            _write_state(
                project_id,
                status="failed",
                message="解析附表同步失败，可点击重试。",
                error=str(error) or "解析附表同步失败。",
                finishedAt=_now_iso(),
            )
            raise error

        is_partial = str(result.get("status") or "") == "partial"
        failed_delete_count = int(result.get("failedDeleteCount") or 0)
        synced_count = int(result.get("syncedCount") or 0)
        _write_state(
            project_id,
            status="failed" if is_partial else "succeeded",
            selectedCount=int(result.get("selectedCount") or selected_count),
            syncedCount=synced_count,
            uploadedCount=int(result.get("uploadedCount") or 0),
            deletedCount=int(result.get("deletedCount") or 0),
            message=(
                f"解析附表已同步 {synced_count} 个，{failed_delete_count} 个旧素材删除失败，可点击重试。"
                if is_partial
                else f"已同步 {synced_count} 个解析附表到项目素材库。"
            ),
            error="部分旧素材删除失败。" if is_partial else "",
            finishedAt=_now_iso(),
        )
        return result

    start_job(f"{TECHNICAL_PARSE_ASSET_SYNC_JOB_PREFIX}:{project_id}", run)
    return state
