"""技术标正文一键填写的后台任务化。

一键填写要串完一批待填写 Word，同步 HTTP 会把连接占满整批，关标签页就丢结果。挪进
Redis 任务队列：提交后立即返回，进度（第几个 / 共几个、当前在填哪条）与终态写进
gap_state["bodyFillState"] 持久化，前端轮询即可，页面刷新、换客户端都不影响。

只跑正文（bid-tech-word-placeholder-filler）任务；附表（bid-tech-table-filler）由另一条
线负责，不在批量范围内。
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from app.services.job_queue import enqueue_generation_job, is_generation_locked
from app.services.local_job_executor import submit_local_job
from app.services.technical_gap_repository import (
    persist_technical_gap_project,
    require_technical_gap_project_for_update,
)
from app.services.technical_gap_state import ensure_technical_gap_state

BODY_FILL_JOB_TYPE = "technical_body_fill"

# 串行执行，不做并发。清单驱动后单条只要约 1 秒（实测 manifest 落盘到产物生成 1 秒），
# 一批 20 多条也就 20 多秒，并发省不下什么；而落库链路里的 persist 走 asyncio.run，
# asyncpg 连接池绑定 event loop，多线程各开新 loop 复用同一个池会直接卡死——
# 实测并发 4 时脚本 1 秒跑完、任务却在写回处挂了 12 分钟不动。


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def empty_body_fill_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "jobId": "",
        "total": 0,
        "done": 0,
        "succeeded": 0,
        "failed": 0,
        "current": "",
        "message": "",
        "errors": [],
    }


def body_fill_state(gap_state: dict[str, Any]) -> dict[str, Any]:
    state = gap_state.get("bodyFillState")
    if not isinstance(state, dict):
        return empty_body_fill_state()
    return copy.deepcopy(state)


def body_fill_running(gap_state: dict[str, Any]) -> bool:
    return str(body_fill_state(gap_state).get("status") or "") in {"queued", "running"}


def _write_state(project_id: str, **fields: Any) -> dict[str, Any]:
    """状态写回项目：worker 与请求线程都经此落库，前端轮询读同一份。"""
    project = require_technical_gap_project_for_update(project_id)
    gap_state = ensure_technical_gap_state(project)
    state = body_fill_state(gap_state)
    state.update(fields)
    gap_state["bodyFillState"] = state
    persist_technical_gap_project(project)
    return copy.deepcopy(state)


def schedule_body_fill_job(project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """提交任务并立即返回状态。Redis 不可用时退回本地串行执行器，行为一致。"""
    payload = dict(data or {})
    state = _write_state(
        project_id,
        status="queued",
        jobId="",
        total=int(payload.get("expectedTotal") or 0),
        done=0,
        succeeded=0,
        failed=0,
        current="",
        message="已提交，等待执行。",
        errors=[],
        startedAt=_now_iso(),
        finishedAt="",
    )
    queue_result = enqueue_generation_job(BODY_FILL_JOB_TYPE, project_id, payload)
    if queue_result.queued or queue_result.locked:
        if queue_result.job_id:
            state = _write_state(project_id, jobId=str(queue_result.job_id))
        return state
    submit_local_job(run_body_fill_job, project_id, payload)
    return state


def body_fill_locked(project_id: str) -> bool:
    return bool(is_generation_locked(BODY_FILL_JOB_TYPE, project_id))


def body_fill_stale(gap_state: dict[str, Any], project_id: str) -> bool:
    """状态是 running 但队列锁已经没了：worker 被重启/杀掉留下的僵尸。

    不识别它的话，前端会一直显示「填写中」，且新任务会被 409 挡住，只能改库才能恢复。
    """
    return body_fill_running(gap_state) and not body_fill_locked(project_id)


def run_body_fill_job(project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """worker 执行体：并发跑完一批正文填写任务，逐条回写进度。"""
    # 延迟 import：worker 侧按需加载，避免与 service 层循环依赖
    from app.services.technical_gap_actions import (
        TECHNICAL_WORD_FILL_SKILL_NAME,
        run_technical_ai_fill_for_gap,
    )
    from app.services.technical_gap_domain import recompute_technical_gap_decisions

    payload = dict(data or {})
    operator = str(payload.get("operator") or "当前用户")
    url_scope = {
        "browser_base_url": str(payload.get("browserBaseUrl") or ""),
        "onlyoffice_base_url": str(payload.get("onlyofficeBaseUrl") or ""),
    }

    try:
        project = require_technical_gap_project_for_update(project_id)
        gap_state = ensure_technical_gap_state(project)
        targets = collect_body_fill_targets(gap_state, payload)
        if not targets:
            return _write_state(
                project_id,
                status="succeeded",
                total=0,
                done=0,
                message="没有待填写的正文任务。",
                finishedAt=_now_iso(),
            )
        _write_state(
            project_id,
            status="running",
            total=len(targets),
            done=0,
            succeeded=0,
            failed=0,
            message=f"正在填写 0/{len(targets)}",
        )
    except Exception as exc:  # noqa: BLE001 - 失败原因如实回写，不静默吞掉
        _write_state(project_id, status="failed", message=str(exc) or "一键填写启动失败。", finishedAt=_now_iso())
        raise

    counters = {"done": 0, "succeeded": 0, "failed": 0}
    errors: list[dict[str, str]] = []

    def fill_one(target: dict[str, str]) -> None:
        gap_id = target["gapId"]
        title = target["title"]
        try:
            # 每条独立取最新项目状态：并发写同一个项目文档，取一次全局副本会互相覆盖
            current = require_technical_gap_project_for_update(project_id)
            run_technical_ai_fill_for_gap(
                current,
                gap_id,
                {"fillTaskId": target["fillTaskId"], "operator": operator},
                **url_scope,
            )
            current["updatedAt"] = _now_iso()
            persist_technical_gap_project(current)
            counters["succeeded"] += 1
        except Exception as exc:  # noqa: BLE001 - 单条失败不能中断整批
            counters["failed"] += 1
            errors.append({"gapId": gap_id, "title": title, "message": str(exc) or "填写失败"})
            _record_item_failure(project_id, gap_id, target["fillTaskId"], str(exc))
        finally:
            counters["done"] += 1
            _write_state(
                project_id,
                done=counters["done"],
                succeeded=counters["succeeded"],
                failed=counters["failed"],
                current=title,
                message=f"正在填写 {counters['done']}/{len(targets)}",
                errors=errors[:20],
            )

    for target in targets:
        fill_one(target)

    latest = require_technical_gap_project_for_update(project_id)
    latest_gap_state = ensure_technical_gap_state(latest)
    plan = latest_gap_state.get("plan")
    if isinstance(plan, dict):
        recompute_technical_gap_decisions(plan)
    message = f"一键填写完成：成功 {counters['succeeded']} 条、失败 {counters['failed']} 条。"
    if counters["failed"]:
        message += "失败项已在目录树标红，可单条重填。"
    latest_gap_state["bodyFillState"] = {
        **body_fill_state(latest_gap_state),
        "status": "succeeded" if not counters["failed"] else "partial",
        "done": counters["done"],
        "succeeded": counters["succeeded"],
        "failed": counters["failed"],
        "current": "",
        "message": message,
        "errors": errors[:20],
        "finishedAt": _now_iso(),
    }
    latest["updatedAt"] = _now_iso()
    persist_technical_gap_project(latest)
    return {"status": "succeeded", "message": message}


def collect_body_fill_targets(gap_state: dict[str, Any], payload: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """待填写的正文任务清单。

    只收 word-placeholder-filler 任务：附表由另一条线负责。已完成的默认跳过，
    传 rerun 才重跑。gapIds 非空时只跑这些目录项（前端按当前标签筛选传入）。
    """
    from app.services.technical_gap_actions import TECHNICAL_WORD_FILL_SKILL_NAME

    data = dict(payload or {})
    requested = {
        str(item or "").strip()
        for item in (data.get("gapIds") if isinstance(data.get("gapIds"), list) else [])
        if str(item or "").strip()
    }
    rerun = bool(data.get("rerun"))
    plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
    targets: list[dict[str, str]] = []
    for item in plan.get("items") or []:
        if not isinstance(item, dict):
            continue
        gap_id = str(item.get("id") or "")
        if requested and gap_id not in requested:
            continue
        if str(item.get("decision") or "") != "fill_required":
            continue
        if item.get("titleOnly"):
            continue
        for task in item.get("fillTasks") or []:
            if not isinstance(task, dict):
                continue
            if str(task.get("skill") or "") != TECHNICAL_WORD_FILL_SKILL_NAME:
                continue
            if str(task.get("status") or "pending") == "completed" and not rerun:
                continue
            targets.append(
                {
                    "gapId": gap_id,
                    "fillTaskId": str(task.get("id") or ""),
                    "title": str(item.get("title") or gap_id),
                }
            )
    return targets


def _record_item_failure(project_id: str, gap_id: str, fill_task_id: str, message: str) -> None:
    """把失败原因写在目录项上，前端据此标红并给出重填入口。"""
    try:
        project = require_technical_gap_project_for_update(project_id)
        gap_state = ensure_technical_gap_state(project)
        plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
        for item in plan.get("items") or []:
            if isinstance(item, dict) and str(item.get("id") or "") == gap_id:
                item["fillError"] = {
                    "fillTaskId": fill_task_id,
                    "message": message[:500],
                    "failedAt": _now_iso(),
                }
                persist_technical_gap_project(project)
                return
    except Exception:  # noqa: BLE001 - 记录失败不能再抛，否则盖掉真正的填写错误
        return
