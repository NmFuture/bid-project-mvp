"""技术标一键填写（正文 + 附表）的后台任务化。

一键填写要串完一批待填写 Word/附表，同步 HTTP 会把连接占满整批，关标签页就丢结果。挪进
Redis 任务队列：提交后立即返回，进度（第几个 / 共几个、当前在填哪条）与终态写进
gap_state["bodyFillState"] 持久化，前端轮询即可，页面刷新、换客户端都不影响。

正文（bid-tech-word-placeholder-filler）与附表（bid-tech-table-filler）任务都收，
正文在前、附表在后，同一个任务并发跑完（产品裁决 2026-08-09：附表也走一键填写）。
"""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.services.background_task_cancel import (
    BackgroundTaskCancelled,
    raise_if_task_cancel_requested,
    task_cancel_requested,
    throttled_cancel_probe,
)
from app.services.job_queue import enqueue_generation_job, is_generation_locked
from app.services.local_job_executor import submit_local_job
from app.services.technical_gap_repository import (
    mutate_technical_gap_project,
    require_technical_gap_project_for_update,
)
from app.services.technical_gap_state import ensure_technical_gap_state

BODY_FILL_JOB_TYPE = "technical_body_fill"

# 计算并行、写回 CAS。#218 后 persist 是同步 psycopg、每次调用独立连接并带 `_rev`
# 乐观锁（冲突抛 ProjectConcurrentUpdateError 由 mutate 重放）；素材库的异步下载
# 全部经 technical_gap_ai_fill._run_async 提交到同一个常驻事件循环——不能在线程里
# 各开 asyncio.run，共享 AsyncEngine 的 asyncpg 连接跨 loop 等待会永久挂起（实测）。
# 因此每条任务在线程池里跑 compute（慢：备素材/OCR/agent 填写，默认 4 并发），
# 主线程按完成顺序收口，经 mutate_technical_gap_project 把结果包纯状态写回——
# CAS 冲突只重放廉价的 apply，不重跑填写，也不碰其他目录项。
# 并发度上限 8：附表填写走 opencode agent，再往上对本地模型服务只是排队。
_BODY_FILL_MAX_CONCURRENCY = 8


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
        "skipped": [],
    }


def body_fill_state(gap_state: dict[str, Any]) -> dict[str, Any]:
    state = gap_state.get("bodyFillState")
    if not isinstance(state, dict):
        return empty_body_fill_state()
    return copy.deepcopy(state)


def body_fill_running(gap_state: dict[str, Any]) -> bool:
    return str(body_fill_state(gap_state).get("status") or "") in {"queued", "running"}


def _plan_of(project: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[Any]]:
    gap_state = ensure_technical_gap_state(project)
    plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    return gap_state, plan, items


def plan_item_snapshot(project: dict[str, Any], gap_id: str) -> dict[str, Any]:
    """取出目录项的独立副本，用于把填写结果搬到另一份 project 状态上。"""
    _, _, items = _plan_of(project)
    for entry in items:
        if isinstance(entry, dict) and str(entry.get("id") or "") == gap_id:
            return copy.deepcopy(entry)
    raise KeyError(gap_id)


def apply_filled_gap_item(
    project: dict[str, Any],
    gap_id: str,
    filled_item: dict[str, Any],
    *,
    fill_task_id: str = "",
) -> None:
    """把填写完的目录项并进给定状态：fillTask/产物级合并，不再整条替换。

    基于 CAS 重放时读到的最新 item，只更新本次填写真正写的字段（该 fillTask 条目、
    resolvedArtifacts 中对应条目、status/qualityStatus/qualityReport/resolvedAt/
    resolvedSource，reviewNotes 按追加合并），其余字段保留最新值——填写期间同项内的
    其他新修改不被填写开始时的旧快照覆盖。调用方负责落库；放在 CAS 事务里可安全重放。
    """
    from app.services.technical_gap_ai_fill import _replace_resolved_artifacts
    from app.services.technical_gap_domain import summarize_technical_gap_plan
    from app.services.technical_gap_state import legacy_technical_gap_items_from_plan

    gap_state, plan, items = _plan_of(project)
    target_index = next(
        (
            index
            for index, entry in enumerate(items)
            if isinstance(entry, dict) and str(entry.get("id") or "") == gap_id
        ),
        None,
    )
    if target_index is None:
        raise KeyError(gap_id)
    latest = items[target_index]

    resolved_task_id = str(fill_task_id or "").strip()
    if not resolved_task_id:
        # 兼容未传任务 id 的调用：本次填写完成的任务 completedAt 与 item.resolvedAt 一致
        filled_tasks = filled_item.get("fillTasks") if isinstance(filled_item.get("fillTasks"), list) else []
        resolved_at = str(filled_item.get("resolvedAt") or "")
        resolved_task_id = next(
            (
                str(task.get("id") or "")
                for task in filled_tasks
                if isinstance(task, dict) and resolved_at and str(task.get("completedAt") or "") == resolved_at
            ),
            "",
        )
    if not resolved_task_id:
        # 定位不到本次填写的任务时无法安全合并，退回整条替换（旧行为）
        items[target_index] = copy.deepcopy(filled_item)
    else:
        merged = copy.deepcopy(latest)
        # 条目级字段：填写只写这几个，直接取结果值
        for field in ("status", "qualityStatus", "qualityReport", "resolvedAt", "resolvedSource"):
            if field in filled_item:
                merged[field] = copy.deepcopy(filled_item[field])
        # reviewNotes 是追加语义：并发新增的保留，本次新加的补上
        notes = list(latest.get("reviewNotes") or [])
        for note in filled_item.get("reviewNotes") or []:
            if note not in notes:
                notes.append(note)
        if "reviewNotes" in filled_item or "reviewNotes" in latest:
            merged["reviewNotes"] = notes
        # fillTask 级：只替换本次填写完成的那条任务，其余任务条目保留最新值
        filled_tasks_by_id = {
            str(task.get("id") or ""): task
            for task in (filled_item.get("fillTasks") or [])
            if isinstance(task, dict)
        }
        filled_task = filled_tasks_by_id.get(resolved_task_id)
        latest_tasks = merged.get("fillTasks") if isinstance(merged.get("fillTasks"), list) else []
        if filled_task is not None:
            for task_index, task in enumerate(latest_tasks):
                if isinstance(task, dict) and str(task.get("id") or "") == resolved_task_id:
                    latest_tasks[task_index] = copy.deepcopy(filled_task)
                    break
        # 产物级：在最新 resolvedArtifacts 上按任务替换/追加，不整条覆盖
        new_artifacts = [
            artifact
            for artifact in (filled_item.get("resolvedArtifacts") or [])
            if isinstance(artifact, dict) and str(artifact.get("fillTaskId") or "") == resolved_task_id
        ]
        if new_artifacts:
            merged["resolvedArtifacts"] = _replace_resolved_artifacts(
                latest.get("resolvedArtifacts"),
                new_artifacts,
                fill_task_id=resolved_task_id,
                skill_name=str(new_artifacts[0].get("skill") or ""),
            )
        items[target_index] = merged
    plan["updatedAt"] = _now_iso()
    plan["summary"] = summarize_technical_gap_plan(plan)
    gap_state["plan"] = plan
    gap_state["items"] = legacy_technical_gap_items_from_plan(plan)
    gap_state["submittedForReview"] = False
    gap_state["reviewConfirmed"] = False
    gap_state["reviewedAt"] = ""
    project["updatedAt"] = _now_iso()


def _write_state(project_id: str, **fields: Any) -> dict[str, Any]:
    """状态写回项目：worker 与请求线程都经此落库，前端轮询读同一份。

    整份 payload 覆盖写，进度回写与用户在页面上的操作会互相盖掉，因此走 CAS 重放。
    """

    def apply(project: dict[str, Any]) -> dict[str, Any]:
        gap_state = ensure_technical_gap_state(project)
        state = body_fill_state(gap_state)
        state.update(fields)
        gap_state["bodyFillState"] = state
        return copy.deepcopy(state)

    return mutate_technical_gap_project(project_id, apply)


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
        skipped=[],
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
    """worker 执行体：线程池并发跑一批正文/附表填写，主线程按完成顺序 CAS 收口。"""
    # 延迟 import：worker 侧按需加载，避免与 service 层循环依赖
    from app.services.technical_gap_ai_fill import (
        apply_technical_ai_fill_result,
        compute_technical_ai_fill,
        enrich_fact_table_with_spec_columns,
        require_spec_driven_fact_table,
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
        skips = collect_body_fill_skips(gap_state, payload)
        if not targets:
            # 待补资料的任务不进清单，但原因要在任务状态里可见
            message = "没有待填写的正文或附表任务。"
            if skips:
                message = f"没有可自动填写的任务：{len(skips)} 条附表任务按来源规则待补资料，请补充素材后再填写。"
            return _write_state(
                project_id,
                status="succeeded",
                total=0,
                done=0,
                message=message,
                skipped=skips,
                finishedAt=_now_iso(),
            )
        # 事实表是项目级单张表，缺清单列时整批都填不了。在这里先判一次，整批一条原因结束，
        # 不进循环——否则 20 多条各报一次同一个错、各标一次红，用户得逐条点开才看得出同因。
        fact_table = gap_state.get("projectFactTable")
        require_spec_driven_fact_table(
            enrich_fact_table_with_spec_columns(fact_table if isinstance(fact_table, dict) else {}, gap_state)
        )
        _write_state(
            project_id,
            status="running",
            total=len(targets),
            done=0,
            succeeded=0,
            failed=0,
            message=f"正在填写 0/{len(targets)}",
            skipped=skips,
        )
    except Exception as exc:  # noqa: BLE001 - 失败原因如实回写，不静默吞掉
        _write_state(project_id, status="failed", message=str(exc) or "一键填写启动失败。", finishedAt=_now_iso())
        raise

    counters = {"done": 0, "succeeded": 0, "failed": 0, "cancelled": 0}
    errors: list[dict[str, str]] = []
    workers = max(1, min(_BODY_FILL_MAX_CONCURRENCY, int(settings.body_fill_concurrency or 1)))

    # 取消探针带节流：一批可能有几十个目录项，每项都查一次库不值当。
    # 语义是「停止后续目录项」——正在跑的那条让它跑完，中途掐断会留下半截产物。
    cancel_probe = throttled_cancel_probe(
        lambda: task_cancel_requested(
            body_fill_state(ensure_technical_gap_state(require_technical_gap_project_for_update(project_id)))
        )
    )

    def compute_one(target: dict[str, str]) -> dict[str, Any]:
        # 排在后面还没开跑的目录项，取消后直接跳过，不必再花一次 AI 调用
        raise_if_task_cancel_requested({"cancelRequested": cancel_probe()})
        # 慢计算在私有深拷贝快照上跑完，不写任何共享状态；写回由主线程统一 CAS 收口。
        # require 在内存后端返回的是 store 里的同一个 dict，必须深拷贝后才是线程私有的。
        snapshot = copy.deepcopy(require_technical_gap_project_for_update(project_id))
        return compute_technical_ai_fill(
            snapshot,
            target["gapId"],
            {"fillTaskId": target["fillTaskId"], "operator": operator},
            **url_scope,
        )

    def collect_one(target: dict[str, str], fill_result: dict[str, Any] | None, exc: BaseException | None) -> None:
        """主线程收口：成功则 CAS 写回结果包，失败则经 mutate 把原因写到目录项上。"""
        gap_id = target["gapId"]
        title = target["title"]
        if isinstance(exc, BackgroundTaskCancelled):
            # 取消跳过的不计成功也不计失败，更不该标红——它压根没跑
            counters["cancelled"] += 1
            return
        try:
            if exc is not None:
                raise exc
            mutate_technical_gap_project(
                project_id,
                lambda project, _result=fill_result: apply_technical_ai_fill_result(project, _result),
            )
            counters["succeeded"] += 1
        except Exception as item_exc:  # noqa: BLE001 - 单条失败不能中断整批
            counters["failed"] += 1
            errors.append({"gapId": gap_id, "title": title, "message": str(item_exc) or "填写失败"})
            _record_item_failure(project_id, gap_id, target["fillTaskId"], str(item_exc))
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

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="body-fill") as pool:
        futures = {pool.submit(compute_one, target): target for target in targets}
        for future in as_completed(futures):
            target = futures[future]
            try:
                fill_result = future.result()
            except BackgroundTaskCancelled as exc:
                collect_one(target, None, exc)
            except Exception as exc:  # noqa: BLE001 - 计算失败的异常走同一条单条失败路径
                collect_one(target, None, exc)
            else:
                collect_one(target, fill_result, None)

    cancelled = counters["cancelled"] > 0
    if cancelled:
        message = (
            f"一键填写已停止：成功 {counters['succeeded']} 条、失败 {counters['failed']} 条、"
            f"未开始 {counters['cancelled']} 条。已填写的产物保留在待审核，可重新发起补齐剩下的。"
        )
    else:
        message = f"一键填写完成：成功 {counters['succeeded']} 条、失败 {counters['failed']} 条。"
        if counters["failed"]:
            message += "失败项已在目录树标红，可单条重填。"

    def finalize(project: dict[str, Any]) -> None:
        gap_state = ensure_technical_gap_state(project)
        plan = gap_state.get("plan")
        if isinstance(plan, dict):
            recompute_technical_gap_decisions(plan)
        gap_state["bodyFillState"] = {
            **body_fill_state(gap_state),
            "status": "cancelled" if cancelled else ("succeeded" if not counters["failed"] else "partial"),
            "cancelRequested": False,
            "cancelledAt": _now_iso() if cancelled else "",
            "done": counters["done"],
            "succeeded": counters["succeeded"],
            "failed": counters["failed"],
            "current": "",
            "message": message,
            "errors": errors[:20],
            "finishedAt": _now_iso(),
        }
        project["updatedAt"] = _now_iso()

    mutate_technical_gap_project(project_id, finalize)
    return {"status": "cancelled" if cancelled else "succeeded", "message": message}


def _collect_body_fill_tasks(
    gap_state: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """待填写的正文 + 附表任务清单，以及因来源规则待补资料被预过滤的任务。

    正文（word-placeholder-filler）与附表（table-filler）任务都收，正文在前、附表在后
    （附表填写走 opencode agent、单条更重，放后面让正文结果先落出来）。已完成的默认跳过，
    传 rerun 才重跑。gapIds 非空时只跑这些目录项（前端按当前标签筛选传入）。
    附表来源规则为 manual_required / missing_source 的任务不进清单（单条填写入口同样
    会被拦截），放入 skips 带回原因，让「待补资料」在任务状态中可见。
    """
    from app.services.technical_gap_actions import (
        TECHNICAL_TABLE_FILL_SKILL_NAME,
        TECHNICAL_WORD_FILL_SKILL_NAME,
    )
    from app.services.technical_gap_ai_fill import fill_task_source_block_reason

    data = dict(payload or {})
    requested = {
        str(item or "").strip()
        for item in (data.get("gapIds") if isinstance(data.get("gapIds"), list) else [])
        if str(item or "").strip()
    }
    rerun = bool(data.get("rerun"))
    plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
    word_targets: list[dict[str, str]] = []
    table_targets: list[dict[str, str]] = []
    skips: list[dict[str, str]] = []
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
            skill = str(task.get("skill") or "")
            if skill not in {TECHNICAL_WORD_FILL_SKILL_NAME, TECHNICAL_TABLE_FILL_SKILL_NAME}:
                continue
            if str(task.get("status") or "pending") == "completed" and not rerun:
                continue
            block_reason = fill_task_source_block_reason(item, task)
            if block_reason:
                skips.append(
                    {
                        "gapId": gap_id,
                        "fillTaskId": str(task.get("id") or ""),
                        "title": str(item.get("title") or gap_id),
                        "reason": block_reason,
                    }
                )
                continue
            bucket = word_targets if skill == TECHNICAL_WORD_FILL_SKILL_NAME else table_targets
            bucket.append(
                {
                    "gapId": gap_id,
                    "fillTaskId": str(task.get("id") or ""),
                    "title": str(item.get("title") or gap_id),
                }
            )
    return word_targets + table_targets, skips


def collect_body_fill_targets(gap_state: dict[str, Any], payload: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """一键填写实际执行的任务清单（不含待补资料的附表任务）。"""
    targets, _ = _collect_body_fill_tasks(gap_state, payload)
    return targets


def collect_body_fill_skips(gap_state: dict[str, Any], payload: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """按来源规则待补资料、被预过滤掉的附表任务（含原因，随 bodyFillState 展示）。"""
    _, skips = _collect_body_fill_tasks(gap_state, payload)
    return skips


def _record_item_failure(project_id: str, gap_id: str, fill_task_id: str, message: str) -> None:
    """把失败原因写在目录项上，前端据此标红并给出重填入口。"""
    def apply(project: dict[str, Any]) -> None:
        _, plan, items = _plan_of(project)
        for item in items:
            if isinstance(item, dict) and str(item.get("id") or "") == gap_id:
                item["fillError"] = {
                    "fillTaskId": fill_task_id,
                    "message": message[:500],
                    "failedAt": _now_iso(),
                }
                return

    try:
        mutate_technical_gap_project(project_id, apply)
    except Exception:  # noqa: BLE001 - 记录失败不能再抛，否则盖掉真正的填写错误
        return
