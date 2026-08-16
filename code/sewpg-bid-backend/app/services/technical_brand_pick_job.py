from __future__ import annotations

"""部件认证品牌选取的后台任务。

素材匹配跑完就自动排一次，人点开「品牌选取」直接看到结果——与事实表
`_autobuild_facts_after_detection` 同一个思路：点击本身不承载任何审批含义，
不该让人多点一下。差别是这里要调 AI（实测几十秒），不能像事实表建骨架那样
同步挂在素材匹配收尾里，否则素材匹配的返回被拖着走，所以走队列。

只在没有结果时自动跑：已经有裁决就不动，免得每次重跑素材匹配都把人工改过的选择冲掉；
要重来走页面上的「重新问一次 AI」。
"""

import logging
from typing import Any

from app.services.job_queue import enqueue_generation_job, is_generation_locked
from app.services.local_job_executor import submit_local_job
from app.services.technical_gap_repository import (
    mutate_technical_gap_project,
    require_technical_gap_project_for_update,
)
from app.services.technical_gap_state import ensure_technical_gap_state

logger = logging.getLogger(__name__)

BRAND_PICK_JOB_TYPE = "brand_pick"


def _write_state(project_id: str, **fields: Any) -> dict[str, Any]:
    def apply(project: dict[str, Any]) -> None:
        gap_state = ensure_technical_gap_state(project)
        current = gap_state.get("brandPicks")
        gap_state["brandPicks"] = {**(current if isinstance(current, dict) else {}), **fields}

    mutate_technical_gap_project(project_id, apply)
    snapshot = require_technical_gap_project_for_update(project_id)
    stored = ensure_technical_gap_state(snapshot).get("brandPicks")
    return dict(stored) if isinstance(stored, dict) else {}


def brand_picks_present(gap_state: dict[str, Any]) -> bool:
    """已有裁决（或已明确报错）就算跑过，不重复自动触发。"""
    stored = gap_state.get("brandPicks")
    if not isinstance(stored, dict):
        return False
    return bool(stored.get("picks")) or bool(stored.get("error"))


def brand_pick_running(gap_state: dict[str, Any]) -> bool:
    stored = gap_state.get("brandPicks")
    if not isinstance(stored, dict):
        return False
    return str(stored.get("status") or "") in {"queued", "running"}


def run_brand_pick_job(project_id: str, _payload: dict[str, Any] | None = None) -> None:
    """worker 入口：跑一次品牌选取并落库。失败写进 error 由页面标黄，不抛给 worker。"""
    from app.services.technical_gap_ai_fill import regenerate_brand_picks

    _write_state(project_id, status="running", message="正在按品牌清单选取部件认证。")
    try:
        project = require_technical_gap_project_for_update(project_id)
        result = regenerate_brand_picks(project)
    except Exception as exc:  # noqa: BLE001 - 选取失败只该让这几个部件标黄
        logger.exception("项目 %s 品牌选取失败", project_id)
        _write_state(project_id, status="failed", error=f"品牌选取失败：{exc}", picks=[])
        return
    _write_state(
        project_id,
        status="failed" if result.get("error") else "succeeded",
        picks=result.get("picks") or [],
        error=str(result.get("error") or ""),
        brandListName=str(result.get("brandListName") or ""),
        generatedAt=str(result.get("generatedAt") or ""),
        message="",
    )


def schedule_brand_pick_job(project_id: str) -> dict[str, Any]:
    """提交任务并立即返回状态。Redis 不可用时退回本地串行执行器，行为一致。"""
    state = _write_state(
        project_id,
        status="queued",
        message="已提交，等待选取部件认证。",
        error="",
    )
    queue_result = enqueue_generation_job(BRAND_PICK_JOB_TYPE, project_id, {})
    if queue_result.queued or queue_result.locked:
        return state
    submit_local_job(run_brand_pick_job, project_id, {})
    return state


def brand_pick_locked(project_id: str) -> bool:
    return bool(is_generation_locked(BRAND_PICK_JOB_TYPE, project_id))


def autoschedule_brand_picks_after_detection(project_id: str) -> None:
    """素材匹配跑完的钩子：没跑过就排一次，跑过就不动。任何失败只记日志。"""
    try:
        snapshot = require_technical_gap_project_for_update(project_id)
        gap_state = ensure_technical_gap_state(snapshot)
        if brand_picks_present(gap_state) or brand_pick_running(gap_state):
            return
        schedule_brand_pick_job(project_id)
    except Exception:
        logger.exception("项目 %s 素材匹配后自动排品牌选取失败，可在页面手动重试", project_id)
