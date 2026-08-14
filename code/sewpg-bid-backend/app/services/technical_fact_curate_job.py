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
    mutate_technical_gap_project,
    require_technical_gap_project_for_update,
)
from app.services.technical_gap_state import ensure_technical_gap_state

FACT_CURATE_JOB_TYPE = "fact_curate"

# 阶段文案：前两阶段由本模块推进，后三阶段 run_fact_curator_for_project 内部按序回调，
# 前端据此显示进度。保存与重建原先是前端另外两次接口调用，三步之间的空隙里再点一次
# 按钮就会改表、打破正在跑的那一轮的前提，所以整条链一起搬进任务，由一把锁罩住。
FACT_CURATE_PHASES = (
    "保存当前编辑",
    "刷新事实表",
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
    """把状态写回项目：worker 与请求线程都经此落库，前端轮询读同一份。

    整份 payload 覆盖写，进度回写与页面操作会互相盖掉，因此走 CAS 重放。
    """

    def apply(project: dict[str, Any]) -> dict[str, Any]:
        gap_state = ensure_technical_gap_state(project)
        state = fact_curate_state(gap_state)
        state.update(fields)
        gap_state["factCurateState"] = state
        return copy.deepcopy(state)

    return mutate_technical_gap_project(project_id, apply)


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


# 本地执行器兜底（Redis 不可用，没有队列锁可查）时判僵尸只能靠超时。取值远大于一轮
# 实际耗时（当前实测约 16 分钟），宁可多等也不要把还在跑的任务判死、放第二轮进来。
_FACT_CURATE_LOCAL_STALE_AFTER_SEC = 2 * 60 * 60


def _running_longer_than(state: dict[str, Any], seconds: int) -> bool:
    started_text = str(state.get("startedAt") or "").strip()
    if not started_text:
        return False
    try:
        started = datetime.fromisoformat(started_text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return (datetime.now(UTC) - started).total_seconds() > seconds


def fact_curate_stale(gap_state: dict[str, Any], project_id: str) -> bool:
    """状态停在 queued/running 但任务其实已经没了：worker 被重启/杀掉留下的僵尸。

    与 body_fill_stale 同一个坑：不识别它，前端永远显示「填充中」，新任务被 409 挡住。
    本轮把保存与重建也纳入同一把锁之后更要命——僵尸状态会连保存和刷新一起锁死，
    没有这道判断就只能改库才能恢复。

    判据分两种，不能只看队列锁：Redis 不可用时任务退回本地执行器，is_generation_locked
    恒为 False，只看锁会把每一个正在跑的本地任务都判成僵尸，等于这把锁完全没生效。
    """
    state = fact_curate_state(gap_state)
    if str(state.get("status") or "") not in {"queued", "running"}:
        return False
    if str(state.get("jobId") or "").strip():
        # 进了 Redis 队列：锁还在就是活的，锁没了就是 worker 死了
        return not fact_curate_locked(project_id)
    return _running_longer_than(state, _FACT_CURATE_LOCAL_STALE_AFTER_SEC)


def run_fact_curate_job(project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """worker 执行体：保存当前编辑 → 刷新事实表 → 跑完整轮 curate，落表并写终态。

    三步原先分散在前端的三次接口调用里，中间的空隙就是缺陷所在：只有 curate 有防重入，
    等待期间再点一次按钮，保存和重建照跑改了表，正在跑的那一轮就失去了前提。整条链
    收进同一个任务，由 fact_curate 这把锁一起罩住。
    """
    # 延迟 import：worker 侧按需加载，避免与 service 层循环依赖
    from app.services.technical_fact_curator import (
        merge_curator_fields_into_table,
        run_fact_curator_for_project,
    )
    from app.services.technical_fact_spec_global import resolve_fact_specs
    from app.services.technical_gap_fact_table import build_project_fact_table, compose_saved_fact_table

    payload = dict(data or {})
    operator = str(payload.get("operator") or "当前用户")
    _write_state(project_id, status="running", phase=FACT_CURATE_PHASES[0], message="正在保存当前编辑。")

    def on_phase(phase: str, message: str = "") -> None:
        _write_state(project_id, status="running", phase=phase, message=message or phase)

    try:
        project = require_technical_gap_project_for_update(project_id)
        gap_state = ensure_technical_gap_state(project)
        if gap_state.get("recognitionStatus") != "completed":
            raise ValueError("请先完成缺口识别，再维护项目事实表。")
        specs, _ = resolve_fact_specs()
        if not specs:
            raise ValueError("尚未上传事实表清单，请先到素材库 · 规则页上传后再生成。")

        # ① 保存页面上带过来的编辑。表还没建过（清单刚上传）时没有可保存的编辑，跳过。
        incoming_fields = payload.get("fields") if isinstance(payload.get("fields"), list) else []
        if incoming_fields:
            current = gap_state.get("projectFactTable")
            saved_at = _now_iso()
            saved_table = compose_saved_fact_table(
                project_id,
                current if isinstance(current, dict) else {},
                incoming_fields,
                confirm=False,
                operator=operator,
                saved_at=saved_at,
            )

            def store_saved(latest_project: dict[str, Any]) -> None:
                ensure_technical_gap_state(latest_project)["projectFactTable"] = copy.deepcopy(saved_table)
                latest_project["updatedAt"] = saved_at

            mutate_technical_gap_project(project_id, store_saved)

        # ② 按最新素材范围重建（重跑规则抽取，并把无值的终态字段复位为未提取），否则
        #    上一轮标成「缺少来源」的字段不会进 AI 的工作清单。实测约 54 秒。
        on_phase(FACT_CURATE_PHASES[1], "正在按最新素材范围刷新事实表。")
        project = require_technical_gap_project_for_update(project_id)
        gap_state = ensure_technical_gap_state(project)
        table = build_project_fact_table(project, gap_state)
        built_at = _now_iso()

        def store_built(latest_project: dict[str, Any]) -> None:
            ensure_technical_gap_state(latest_project)["projectFactTable"] = copy.deepcopy(table)
            latest_project["updatedAt"] = built_at

        mutate_technical_gap_project(project_id, store_built)

        # ③ AI 补抽 / 纠错。这一步十几分钟，期间的表改动由落表侧按字段让位，不再整轮作废。
        project = require_technical_gap_project_for_update(project_id)
        gap_state = ensure_technical_gap_state(project)
        updated_table, report = run_fact_curator_for_project(
            copy.deepcopy(project), copy.deepcopy(gap_state), payload, on_phase=on_phase
        )
        touched_keys = report.get("touchedKeys") if isinstance(report.get("touchedKeys"), list) else []

        def apply(latest_project: dict[str, Any]) -> str:
            latest_gap_state = ensure_technical_gap_state(latest_project)
            latest_table = latest_gap_state.get("projectFactTable")
            # 只把本轮写过的字段并进最新的表，其余保留最新值；人工在此期间填写或裁定过的
            # 字段自动让位（合并函数按最新值重过只读门禁）。旧实现是整表快照比对，
            # 表被动过一个字节就抛异常整轮作废，实测让一次 16 分钟的运行全部白跑。
            # 放在 CAS 事务里，重放时按当时读到的最新表重新合并，结果与重放次数无关。
            merged, dropped = merge_curator_fields_into_table(
                latest_table if isinstance(latest_table, dict) else updated_table,
                updated_table,
                touched_keys,
            )
            counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
            message = (
                "事实表维护完成："
                f"补抽 {counts.get('filled', 0)} 条、修正 {counts.get('fixed', 0)} 条、"
                f"未找到值 {counts.get('notFound', 0)} 条、"
                f"忽略 {counts.get('ignored', 0)} 条（已确认跳过 {counts.get('skippedConfirmed', 0)} 条）。"
            )
            if counts.get("ignored"):
                message += "存在未落表建议，请检查 curateReport.ignored 的原因。"
            if dropped:
                message += f"另有 {len(dropped)} 条因期间人工改动或字段变更未覆盖，见 curateReport.dropped。"
            latest_gap_state["projectFactTable"] = merged
            latest_gap_state["factCurateState"] = {
                **fact_curate_state(latest_gap_state),
                "status": "succeeded",
                "phase": "",
                "message": message,
                "finishedAt": _now_iso(),
                "report": copy.deepcopy({**report, "dropped": dropped}),
            }
            latest_project["updatedAt"] = _now_iso()
            return message

        message = mutate_technical_gap_project(project_id, apply)
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
