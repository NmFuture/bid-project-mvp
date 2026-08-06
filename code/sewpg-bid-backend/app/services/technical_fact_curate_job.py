"""事实表 AI 匹配填充的后台任务化。

curate 单轮要跑几分钟（组素材清单 → opencode 分析 → 回收落表），同步 HTTP 请求会把
连接占满整轮，且关标签页就拿不到结果。这里把它挪进 Redis 任务队列：提交后立即返回，
执行状态与阶段写进 gap_state["factCurateState"] 持久化，前端轮询即可，弹窗关闭、
页面刷新都不影响任务本身。
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

FACT_CURATE_JOB_TYPE = "fact_curate"

# 阶段文案：run_fact_curator_for_project 内部按序回调，前端据此显示进度
FACT_CURATE_PHASES = (
    "组装素材清单",
    "AI 分析素材",
    "回收建议落表",
)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def empty_fact_curate_state() -> dict[str, Any]:
    return {"status": "idle", "jobId": "", "phase": "", "message": ""}


def fact_curate_state(gap_state: dict[str, Any]) -> dict[str, Any]:
    state = gap_state.get("factCurateState")
    if not isinstance(state, dict):
        return empty_fact_curate_state()
    return copy.deepcopy(state)


def fact_curate_running(gap_state: dict[str, Any]) -> bool:
    return str(fact_curate_state(gap_state).get("status") or "") in {"queued", "running"}


def _write_state(project_id: str, **fields: Any) -> dict[str, Any]:
    """把状态写回项目：worker 与请求线程都经此落库，前端轮询读同一份。"""
    project = require_technical_gap_project_for_update(project_id)
    gap_state = ensure_technical_gap_state(project)
    state = fact_curate_state(gap_state)
    state.update(fields)
    gap_state["factCurateState"] = state
    persist_technical_gap_project(project)
    return copy.deepcopy(state)


def schedule_fact_curate_job(project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """提交任务并立即返回状态。Redis 不可用时退回本地串行执行器，行为一致。"""
    payload = dict(data or {})
    state = _write_state(
        project_id,
        status="queued",
        jobId="",
        phase=FACT_CURATE_PHASES[0],
        message="已提交，等待执行。",
        startedAt=_now_iso(),
        finishedAt="",
        report=None,
    )
    queue_result = enqueue_generation_job(FACT_CURATE_JOB_TYPE, project_id, payload)
    if queue_result.queued or queue_result.locked:
        if queue_result.job_id:
            state = _write_state(project_id, jobId=str(queue_result.job_id))
        return state
    # Redis 不可用：本地执行器串行跑，状态字段仍然照写，前端轮询逻辑无需分支
    submit_local_job(run_fact_curate_job, project_id, payload)
    return state


def fact_curate_locked(project_id: str) -> bool:
    return bool(is_generation_locked(FACT_CURATE_JOB_TYPE, project_id))


def run_fact_curate_job(project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """worker 执行体：跑完整轮 curate，落表并把终态写进 factCurateState。"""
    # 延迟 import：worker 侧按需加载，避免与 service 层循环依赖
    from app.services.technical_fact_curator import run_fact_curator_for_project
    from app.services.technical_gap_fact_table import PROJECT_FACT_TABLE_SCHEMA_VERSION, build_project_fact_table

    payload = dict(data or {})
    _write_state(project_id, status="running", phase=FACT_CURATE_PHASES[0], message="正在组装素材清单。")

    def on_phase(phase: str, message: str = "") -> None:
        _write_state(project_id, status="running", phase=phase, message=message or phase)

    try:
        project = require_technical_gap_project_for_update(project_id)
        gap_state = ensure_technical_gap_state(project)
        if gap_state.get("recognitionStatus") != "completed":
            raise ValueError("请先完成缺口识别，再维护项目事实表。")
        table = gap_state.get("projectFactTable")
        if not isinstance(table, dict) or table.get("schemaVersion") != PROJECT_FACT_TABLE_SCHEMA_VERSION:
            table = build_project_fact_table(project, gap_state)
            gap_state["projectFactTable"] = table
        source_table = copy.deepcopy(table)
        source_fact_specs = copy.deepcopy(gap_state.get("factSpecs"))

        updated_table, report = run_fact_curator_for_project(
            copy.deepcopy(project), copy.deepcopy(gap_state), payload, on_phase=on_phase
        )

        latest_project = require_technical_gap_project_for_update(project_id)
        latest_gap_state = ensure_technical_gap_state(latest_project)
        # 与同步版同一道保护：期间事实表/填表规则被改过就不覆盖，避免盖掉人工结果
        if (
            latest_gap_state.get("projectFactTable") != source_table
            or latest_gap_state.get("factSpecs") != source_fact_specs
        ):
            raise ValueError("AI 匹配期间事实表或填表规则已被修改，本次结果未覆盖保存；请检查最新数据后重试。")

        counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
        message = (
            "事实表维护完成："
            f"补抽 {counts.get('filled', 0)} 条、修正 {counts.get('fixed', 0)} 条、"
            f"口径建议 {counts.get('advised', 0)} 条、未找到值 {counts.get('notFound', 0)} 条、"
            f"忽略 {counts.get('ignored', 0)} 条（已确认跳过 {counts.get('skippedConfirmed', 0)} 条）。"
        )
        if counts.get("ignored"):
            message += "存在未落表建议，请检查 curateReport.ignored 的原因。"

        latest_gap_state["projectFactTable"] = updated_table
        latest_gap_state["factCurateState"] = {
            **fact_curate_state(latest_gap_state),
            "status": "succeeded",
            "phase": "",
            "message": message,
            "finishedAt": _now_iso(),
            "report": copy.deepcopy(report),
        }
        latest_project["updatedAt"] = _now_iso()
        persist_technical_gap_project(latest_project)
        return {"status": "succeeded", "message": message}
    except Exception as exc:  # noqa: BLE001 - 失败原因要如实回写给前端，不静默吞掉
        _write_state(
            project_id,
            status="failed",
            phase="",
            message=str(exc) or "AI 匹配填充失败。",
            finishedAt=_now_iso(),
        )
        raise
