"""来源项目素材复制的后台任务。

确认参与时项目目录同步建好（用户马上要跳进去），目录下的素材从来源项目复制过来
可能是上百个文件，放进后台跑，状态写回项目供前端轮询。
"""

from __future__ import annotations

import copy
from typing import Any

from app.services.background_job_registry import start_job
from app.services.bid_runtime_state import now_iso
from app.services.technical_material_store import technical_material_store
from app.services.workspace_project_access import (
    persist_workspace_project_fields,
    persist_workspace_project_state,
    require_any_workspace_project_for_update,
)

MATERIAL_COPY_JOB_PREFIX = "technical-material-copy"
# 来源项目的「附表」是它自己那次招标的产物，抄给新项目是错的
TECHNICAL_APPENDIX_FOLDER_NAME = "附表"
PROGRESS_WRITE_EVERY = 5


def empty_material_copy_state() -> dict[str, Any]:
    return {"status": "idle", "copied": 0, "skipped": 0, "total": 0, "failed": [], "message": ""}


def material_copy_state(project: dict[str, Any]) -> dict[str, Any]:
    state = project.get("materialCopyState")
    if not isinstance(state, dict):
        return empty_material_copy_state()
    return copy.deepcopy(state)


def _write_state(project_id: str, **fields: Any) -> dict[str, Any]:
    project = require_any_workspace_project_for_update(
        project_id,
        not_found_error=lambda pid: KeyError(pid),
    )
    state = material_copy_state(project)
    state.update(fields)
    project["materialCopyState"] = state
    persist_workspace_project_fields(project, "materialCopyState")
    return copy.deepcopy(state)


def schedule_technical_material_copy(
    project_id: str,
    *,
    source_path: str,
    target_path: str,
    source_project_id: str = "",
) -> dict[str, Any]:
    """登记初始状态并把复制丢进后台，立即返回当前状态。"""

    state = _write_state(
        project_id,
        status="running",
        sourceProjectId=source_project_id,
        sourcePath=source_path,
        targetPath=target_path,
        copied=0,
        skipped=0,
        total=0,
        failed=[],
        message="正在归集来源项目素材。",
        startedAt=now_iso(),
        finishedAt="",
    )

    def on_progress(done: int, total: int) -> None:
        # 状态落库是同步写，逐个文件写会拖慢整批；按批次刷新，末尾一次必写。
        if done and done != total and done % PROGRESS_WRITE_EVERY:
            return
        _write_state(
            project_id,
            status="running",
            copied=done,
            total=total,
            message=f"正在归集来源项目素材（{done}/{total}）。",
        )

    async def run() -> dict[str, Any]:
        try:
            result = await technical_material_store.raw_copy_project_materials(
                source_path=source_path,
                target_path=target_path,
                exclude_top_level_names={TECHNICAL_APPENDIX_FOLDER_NAME},
                on_progress=on_progress,
            )
        except Exception as exc:  # noqa: BLE001 - 失败原因如实回写，不静默吞掉
            _write_state(
                project_id,
                status="failed",
                message=str(exc) or "来源项目素材复制失败。",
                finishedAt=now_iso(),
            )
            raise
        failed = result.get("failed") or []
        message = f"已归集 {result.get('copied', 0)} 个素材"
        if result.get("skipped"):
            message += f"，跳过同名 {result['skipped']} 个"
        if failed:
            message += f"，{len(failed)} 个失败"
        _write_state(
            project_id,
            status="failed" if failed else "succeeded",
            copied=int(result.get("copied") or 0),
            skipped=int(result.get("skipped") or 0),
            total=int(result.get("total") or 0),
            failed=failed,
            message=f"{message}。",
            finishedAt=now_iso(),
        )
        return result

    start_job(f"{MATERIAL_COPY_JOB_PREFIX}:{project_id}", run)
    return state
