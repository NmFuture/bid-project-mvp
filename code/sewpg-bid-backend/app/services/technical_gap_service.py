from __future__ import annotations

import asyncio
import copy
import logging
import tempfile
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import settings
from app.services.bid_project_repository import ProjectConcurrentUpdateError, project_revision
from app.services.bid_document_flow import _validate_callback_token, _validate_download_url
from app.services.onlyoffice_documents import download_document_from_onlyoffice
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.identity import build_project_identity, build_project_material_scope, canonical_customer
from app.services.technical_appendix_source_matrix import (
    apply_appendix_source_matrix_to_plan,
    parse_appendix_source_matrix,
)
from app.services.technical_rules_store import (
    load_appendix_matrix_for_customer,
    replace_appendix_rules,
)
from app.services.turbine_models import project_turbine_model
from app.services.technical_gap_fact_table import (
    PROJECT_FACT_TABLE_SCHEMA_VERSION,
    build_project_fact_table,
    empty_project_fact_table,
    normalize_project_fact_field,
    project_fact_material_work_dir,
    summarize_project_fact_fields,
)
from app.services.project_fact_materials import (
    materialize_project_fact_material,
    project_fact_material_cached_path,
)
from app.services.peripheral import PeripheralError
from app.services.bid_runtime_state import count_outline_nodes, now_iso
from app.services.technical_gap_actions import (
    TECHNICAL_TABLE_FILL_SKILL_NAME,
    TECHNICAL_WORD_FILL_SKILL_NAME,
    build_technical_gap_plan_for_project,
    cleanup_prepared_technical_gap_material_files,
    prepare_technical_existing_gap_material_files,
    register_technical_existing_gap_material,
    register_technical_manual_gap_upload,
    run_technical_ai_fill_for_gap,
)
from app.services.technical_gap_domain import (
    build_technical_gap_detection_payload,
    check_technical_gap_integrity,
    find_technical_gap_item,
    find_technical_gap_plan_item,
    recompute_technical_gap_decisions,
    refresh_technical_gap_plan_artifact_urls,
    summarize_technical_gap_plan,
    technical_gap_artifact_is_s7_ready,
)
from app.services.technical_fact_curate_job import (
    fact_curate_locked,
    fact_curate_running,
    fact_curate_state,
    schedule_fact_curate_job,
)
from app.services.technical_body_fill_job import (
    apply_filled_gap_item,
    body_fill_locked,
    body_fill_running,
    body_fill_stale,
    body_fill_state,
    collect_body_fill_skips,
    collect_body_fill_targets,
    plan_item_snapshot,
    schedule_body_fill_job,
)
from app.services.job_queue import acquire_ai_fill_lock, release_ai_fill_lock
from app.services.technical_fact_material_classes import build_fact_material_check
from app.services.technical_fact_spec_global import resolve_fact_specs
from app.services.technical_gap_repository import (
    get_technical_gap_project_runtime_state,
    mutate_technical_gap_project,
    require_technical_gap_project_for_update,
)
from app.services.technical_gap_state import (
    default_technical_review_document_state,
    ensure_technical_gap_state,
    legacy_technical_gap_items_from_plan,
    repair_technical_gap_state_fill_task_skills,
)
from app.services.url_utils import onlyoffice_backend_base_url


logger = logging.getLogger(__name__)

PROJECT_FACT_CONFIRMED_STATUSES = {"confirmed"}

_artifact_callback_locks: dict[tuple[str, str], threading.Lock] = {}
_artifact_callback_locks_guard = threading.Lock()


class _StaleArtifactSession(RuntimeError):
    pass


def _artifact_callback_lock(project_id: str, artifact_id: str) -> threading.Lock:
    key = (project_id, artifact_id)
    with _artifact_callback_locks_guard:
        return _artifact_callback_locks.setdefault(key, threading.Lock())


def _find_gap_artifact(project: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    gap_state = ensure_technical_gap_state(project)
    plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
    for item in plan.get("items") or []:
        for artifact in item.get("resolvedArtifacts") or []:
            if isinstance(artifact, dict) and str(artifact.get("id") or "") == artifact_id:
                return artifact
    raise KeyError(artifact_id)


def _validate_editable_gap_artifact(
    artifact: dict[str, Any],
    callback_version: int | None,
) -> int:
    if str(artifact.get("source") or "") != "ai_fill":
        raise ValueError("仅 AI 填写产物支持在线编辑回写。")
    if artifact.get("supersededAt") or artifact.get("active", True) is False:
        raise ValueError("该产物已被新的选材或填写结果取代，不能再回写。")
    current_version = int(artifact.get("ooDocVersion") or 1)
    if callback_version is not None and callback_version != current_version:
        raise _StaleArtifactSession("OnlyOffice 编辑会话已过期。")
    return current_version


def default_fact_material_scopes(project: dict[str, Any]) -> list[dict[str, str]]:
    """事实表默认生效的素材范围：标准文件/客户定制/项目定制三层。

    与 AI 匹配填充实际扫描的口径同源（project_fact_material_index 的 curate 分支），
    前端据此如实展示范围，不再写死「项目素材」。
    """
    try:
        scopes = build_project_material_scope(project).get("readableScopes") or []
    except Exception:
        return []
    return [
        {"tier": str(scope.get("materialTier") or ""), "path": str(scope.get("path") or "")}
        for scope in scopes
        if isinstance(scope, dict) and str(scope.get("path") or "").strip()
    ]


def _artifact_block_reason(artifact: dict[str, Any]) -> str:
    if artifact.get("active", True) is False:
        return "已被撤销或取代"
    if artifact.get("s7Ready", True) is False:
        return "标记为未就绪：待填写模板尚未填完，或质检未通过"
    quality_report = artifact.get("qualityReport") if isinstance(artifact.get("qualityReport"), dict) else {}
    status = str(quality_report.get("status") or "")
    unfilled = quality_report.get("unfilledPlaceholderCount")
    detail = f"质检状态 {status or '缺失'}"
    if unfilled:
        detail += f"，{unfilled} 项未填字段"
    return f"AI 填写产物未放行（{detail}），需人工复核"


def _assembly_outlook(item: dict[str, Any], title_only_ids: set[str]) -> dict[str, Any]:
    """单个目录项在正文组装时会不会被采用，口径对齐 tech_assembly 的挑选规则。"""
    outlook: dict[str, Any] = {
        "id": str(item.get("id") or ""),
        "number": str(item.get("number") or ""),
        "title": str(item.get("title") or ""),
        "decision": str(item.get("decision") or ""),
        "status": str(item.get("status") or ""),
        "willAssemble": False,
        "reason": "",
        "sources": [],
    }
    if item.get("titleOnly") is True:
        outlook["reason"] = "仅保留标题，不参与正文合并"
        return outlook
    coverage_role = str(item.get("coverageRole") or item.get("coverage_role") or "").strip()
    covered_by = str(item.get("coveredByParent") or item.get("covered_by_parent") or "").strip()
    if coverage_role == "covered_by_parent" and covered_by not in title_only_ids:
        outlook["reason"] = f"由父章 {covered_by or '上级'} 覆盖，内容随父章一起写"
        return outlook

    artifacts = item.get("resolvedArtifacts") if isinstance(item.get("resolvedArtifacts"), list) else []
    if artifacts:
        # 有人工选材/AI 填写产物时只认它们，自动匹配的候选自动让位（与组装一致）
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            accepted = technical_gap_artifact_is_s7_ready(artifact)
            outlook["sources"].append(
                {
                    "kind": "resolvedArtifact",
                    "id": str(artifact.get("id") or ""),
                    "source": str(artifact.get("source") or ""),
                    "fileName": str(artifact.get("fileName") or ""),
                    "path": str(artifact.get("path") or artifact.get("docx") or ""),
                    "accepted": accepted,
                    "blockedBy": "" if accepted else _artifact_block_reason(artifact),
                }
            )
        accepted_count = sum(1 for source in outlook["sources"] if source["accepted"])
        outlook["willAssemble"] = accepted_count > 0
        outlook["reason"] = (
            f"采用 {accepted_count} 份产物"
            if accepted_count
            else "有产物但都未放行：复核通过或重填后才会进正文"
        )
        return outlook

    matched = item.get("matchedMaterials") if isinstance(item.get("matchedMaterials"), list) else []
    for material in matched:
        if not isinstance(material, dict):
            continue
        outlook["sources"].append(
            {
                "kind": "matchedMaterial",
                "id": str(material.get("id") or material.get("materialId") or ""),
                "source": "auto_match",
                "fileName": str(material.get("fileName") or material.get("name") or ""),
                "path": str(material.get("path") or ""),
                "accepted": True,
                "blockedBy": "",
            }
        )
    outlook["willAssemble"] = bool(outlook["sources"])
    outlook["reason"] = (
        f"采用 {len(outlook['sources'])} 份自动匹配素材" if outlook["sources"] else "没有任何可用素材"
    )
    return outlook


def _raise_gap_error(exc: Exception, not_found_detail: str) -> None:
    contract_error = exc
    while isinstance(contract_error, ExceptionGroup) and contract_error.exceptions:
        first_error = contract_error.exceptions[0]
        if not isinstance(first_error, Exception):
            break
        contract_error = first_error
    if isinstance(contract_error, PeripheralError):
        raise HTTPException(status_code=contract_error.status_code, detail=contract_error.detail) from exc
    # 并发写冲突要能和普通入参错误区分开：前端据此原地重试，而不是提示用户改输入。
    if isinstance(contract_error, ProjectConcurrentUpdateError):
        raise HTTPException(status_code=409, detail=str(contract_error)) from exc
    if isinstance(contract_error, (RuntimeError, ValueError)):
        raise HTTPException(status_code=400, detail=str(contract_error)) from exc
    if isinstance(contract_error, KeyError):
        raise HTTPException(status_code=404, detail=not_found_detail) from exc
    raise exc


# 单条 AI 填写的 (project, gap) 互斥：Redis 锁为主，多实例共享；
# Redis 缺席时退化为进程内锁，供本地单进程环境使用。
_LOCAL_AI_FILL_SLOTS: set[tuple[str, str]] = set()
_LOCAL_AI_FILL_SLOTS_GUARD = threading.Lock()


def _acquire_ai_fill_slot(project_id: str, gap_id: str) -> tuple[str, str] | None:
    """抢占单条填写互斥位，冲突返回 None；成功返回释放用 token。"""
    owner = uuid4().hex
    acquired = acquire_ai_fill_lock(project_id, gap_id, owner)
    if acquired is True:
        return ("redis", owner)
    if acquired is False:
        return None
    key = (project_id, gap_id)
    with _LOCAL_AI_FILL_SLOTS_GUARD:
        if key in _LOCAL_AI_FILL_SLOTS:
            return None
        _LOCAL_AI_FILL_SLOTS.add(key)
    return ("local", owner)


def _release_ai_fill_slot(project_id: str, gap_id: str, token: tuple[str, str]) -> None:
    kind, owner = token
    if kind == "redis":
        release_ai_fill_lock(project_id, gap_id, owner)
        return
    with _LOCAL_AI_FILL_SLOTS_GUARD:
        _LOCAL_AI_FILL_SLOTS.discard((project_id, gap_id))


def _require_no_body_fill_running(project_id: str, gap_state: dict[str, Any]) -> None:
    """一键填写运行中（状态或队列锁任一成立）时，单条填写返回 409。"""
    if body_fill_locked(project_id) or (body_fill_running(gap_state) and not body_fill_stale(gap_state, project_id)):
        raise PeripheralError(409, "一键填写任务正在执行，暂不可单条填写，请等待完成后再试。", "BODY_FILL_RUNNING")


class TechnicalGapService:
    def ensure_project(self, project_id: str) -> dict[str, Any]:
        return get_technical_gap_project_runtime_state(project_id)

    @staticmethod
    def _persist_fill_task_skill_repair(project_id: str) -> None:
        """把 fillTask skill 名的自愈修复单独落库；没改动就不写，避免版本号空转。"""

        def apply(project: dict[str, Any]) -> bool:
            changed = bool(repair_technical_gap_state_fill_task_skills(ensure_technical_gap_state(project)))
            if changed:
                project["updatedAt"] = now_iso()
            return changed

        mutate_technical_gap_project(project_id, apply, persist_when=lambda changed: changed)

    @staticmethod
    def _require_confirmed_project_fact_table(gap_state: dict[str, Any]) -> dict[str, Any]:
        table = gap_state.get("projectFactTable") if isinstance(gap_state.get("projectFactTable"), dict) else {}
        if table.get("status") not in PROJECT_FACT_CONFIRMED_STATUSES:
            raise ValueError("请先维护并确认项目事实表，再执行 AI 填写。")
        return table

    @staticmethod
    def _refresh_gap_integrity(project: dict[str, Any], gap_state: dict[str, Any]) -> None:
        plan = gap_state.get("plan")
        if isinstance(plan, dict):
            # 决策终审：选中/上传/AI填写完成后，decision 要跟着从「候选待定」翻成 ready，
            # 而不是永远停在 fill_required/review_required——对齐商务标的两层架构。
            recompute_technical_gap_decisions(plan)
        gap_state["integrity"] = check_technical_gap_integrity(gap_state.get("plan") or {})
        if isinstance(gap_state.get("plan"), dict):
            gap_state["plan"]["integrity"] = gap_state["integrity"]
            gap_state["plan"]["summary"] = summarize_technical_gap_plan(gap_state["plan"])
        project["updatedAt"] = now_iso()

    def _url_scope(self, request: Request) -> dict[str, str]:
        return {
            "browser_base_url": str(request.base_url).rstrip("/"),
            "onlyoffice_base_url": onlyoffice_backend_base_url(request),
        }

    def _gap_filling_payload(
        self,
        project_id: str,
        project: dict[str, Any],
        gap_state: dict[str, Any],
        *,
        browser_base_url: str = "",
        onlyoffice_base_url: str = "",
    ) -> dict[str, Any]:
        # 只改内存状态、不落库：所有调用点都在 mutate 事务内，落库由外层统一 CAS 写。
        # 在事务内再写一次会顶掉版本号，让外层 CAS 必然冲突。
        if gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先触发缺口识别后再进入缺口处理。")
        repaired = repair_technical_gap_state_fill_task_skills(gap_state)
        plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
        decisions_changed = recompute_technical_gap_decisions(plan) if plan else 0
        if repaired or decisions_changed:
            self._refresh_gap_integrity(project, gap_state)
            gap_state["items"] = legacy_technical_gap_items_from_plan(plan)
            project["updatedAt"] = now_iso()
        gap_plan = copy.deepcopy(gap_state.get("plan") or {})
        refresh_technical_gap_plan_artifact_urls(
            project_id,
            gap_plan,
            browser_base_url=browser_base_url,
            onlyoffice_base_url=onlyoffice_base_url,
        )
        return {
            "status": "ready",
            "recognizedAt": gap_state["recognizedAt"],
            "submittedForReview": bool(gap_state["submittedForReview"]),
            "items": copy.deepcopy(gap_state["items"]),
            "submissions": copy.deepcopy(gap_state["submissions"]),
            "gapPlan": gap_plan,
            "integrity": copy.deepcopy(gap_state.get("integrity") or {}),
            "projectFactTable": copy.deepcopy(gap_state.get("projectFactTable") or {}),
        }

    async def detection_status(self, project_id: str, request: Request | None = None) -> dict[str, Any]:
        try:
            # 前端轮询接口，顺带做自愈修复。命中修复时才落库，且走 CAS——
            # 轮询与后台填写并行时，无条件覆盖会把刚填好的产物盖回去。
            def apply(project: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
                gap_state = ensure_technical_gap_state(project)
                repaired = repair_technical_gap_state_fill_task_skills(gap_state)
                plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
                decisions_changed = recompute_technical_gap_decisions(plan) if plan else 0
                changed = bool(repaired or decisions_changed)
                if changed:
                    self._refresh_gap_integrity(project, gap_state)
                    gap_state["items"] = legacy_technical_gap_items_from_plan(plan)
                    project["updatedAt"] = now_iso()
                return changed, build_technical_gap_detection_payload(project, gap_state)

            _, payload = mutate_technical_gap_project(
                project_id, apply, persist_when=lambda outcome: outcome[0]
            )
            url_scope = self._url_scope(request) if request is not None else {}
            refresh_technical_gap_plan_artifact_urls(project_id, payload["gapPlan"], **url_scope)
            return payload
        except Exception as exc:
            _raise_gap_error(exc, "Gap detection not found")

    def export_plan(self, project_id: str) -> dict[str, Any]:
        """导出库里的最新缺口清单，并逐项标出正文组装会不会采用它。

        磁盘上 s4_gap_workdir/gap_plan.json 是识别当时的快照，此后的人工选材、AI 填写、
        复核都只落库，拿那份文件排查只会看到过期数据。这里出的是当前状态，附带组装判定，
        用来回答「这一章为什么没进正文」。
        """
        try:
            project = get_technical_gap_project_runtime_state(project_id)
            gap_state = ensure_technical_gap_state(project)
            plan = copy.deepcopy(gap_state.get("plan") or {})
            items = [item for item in (plan.get("items") or []) if isinstance(item, dict)]
            title_only_ids = {
                str(item.get("id") or "").strip() for item in items if item.get("titleOnly") is True
            }
            outlooks = [_assembly_outlook(item, title_only_ids) for item in items]
            will_assemble = sum(1 for entry in outlooks if entry["willAssemble"])
            blocked = [
                entry
                for entry in outlooks
                if not entry["willAssemble"]
                and any(source["kind"] == "resolvedArtifact" for source in entry["sources"])
            ]
            return {
                "projectId": project_id,
                "exportedAt": now_iso(),
                "revision": project_revision(project),
                "recognitionStatus": str(gap_state.get("recognitionStatus") or ""),
                "summary": {
                    "totalItems": len(outlooks),
                    "willAssemble": will_assemble,
                    "skipped": len(outlooks) - will_assemble,
                    "blockedByReview": len(blocked),
                },
                "blockedItems": blocked,
                "items": outlooks,
                "plan": plan,
            }
        except Exception as exc:
            _raise_gap_error(exc, "Gap detection not found")

    @staticmethod
    def _require_confirmed_outline(project: dict[str, Any]) -> None:
        """素材匹配的前置闸门：目录必须已生成、已确认且至少有一个节点。

        与商务标 business_gap_service.run_detection 的校验对齐；
        ValueError 由 _raise_gap_error 映射为 400。
        """
        outline_state = project.get("outline_state") if isinstance(project.get("outline_state"), dict) else {}
        nodes = outline_state.get("nodes") if isinstance(outline_state.get("nodes"), list) else []
        if str(outline_state.get("reviewStatus") or "") != "confirmed" or not outline_state.get("generatedAt"):
            raise ValueError("请先生成并确认投标目录，再启动素材匹配。")
        if count_outline_nodes(nodes) < 1:
            raise ValueError("投标目录为空，请先在目录审核页补充至少一个目录节点。")

    def run_detection(self, project_id: str) -> dict[str, Any]:
        try:
            # planner 是重活，先在快照上算完计划，再把结果原子写回最新状态
            snapshot = require_technical_gap_project_for_update(project_id)
            self._require_confirmed_outline(snapshot)
            plan = build_technical_gap_plan_for_project(snapshot)
            items = legacy_technical_gap_items_from_plan(plan)
            recognized_at = now_iso()
            plan["summary"] = summarize_technical_gap_plan(plan)
            plan["integrity"] = {}

            def apply(project: dict[str, Any]) -> dict[str, Any]:
                gap_state = ensure_technical_gap_state(project)
                gap_state.update(
                    {
                        "recognitionStatus": "completed",
                        "recognizedAt": recognized_at,
                        "submittedForReview": False,
                        "reviewConfirmed": False,
                        "reviewedAt": "",
                        "items": copy.deepcopy(items),
                        "plan": copy.deepcopy(plan),
                        "planFile": str(plan.get("planFile") or ""),
                        "integrity": {},
                    }
                )
                project["review_document_state"] = default_technical_review_document_state(project)
                project["updatedAt"] = recognized_at
                return build_technical_gap_detection_payload(project, gap_state)

            payload = mutate_technical_gap_project(project_id, apply)
        except Exception as exc:
            _raise_gap_error(exc, "Gap detection not found")
        self._autobuild_facts_after_detection(project_id)
        return {
            **payload,
            "message": f"缺口识别完成，共识别 {payload['summary']['totalTocItems']} 个目录项。",
        }

    def _autobuild_facts_after_detection(self, project_id: str) -> None:
        """素材匹配跑完后自动把事实表的值找一遍，人点开事实表直接看到真值。

        只在第一次自动建：已经有表就不动，避免每次重跑素材匹配都把 AI 填的值冲掉；
        之后要重建走页面上的「刷新并 AI 填充」。清单没上传、建表失败都不影响素材匹配
        本身的结果，只记日志——事实表建不出来时页面会给出去规则页上传的引导。
        """
        try:
            specs, _ = resolve_fact_specs()
            if not specs:
                logger.info("项目 %s 尚未上传事实表清单，跳过自动建表", project_id)
                return
            snapshot = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(snapshot)
            existing = gap_state.get("projectFactTable")
            if isinstance(existing, dict) and existing.get("fields"):
                return
            # run_detection 是同步路由，FastAPI 已把它放在工作线程里，
            # 这里可以直接调用内部走 run_awaitable_sync 桥接的重活。
            table = build_project_fact_table(snapshot, gap_state)

            def apply(project: dict[str, Any]) -> None:
                ensure_technical_gap_state(project)["projectFactTable"] = copy.deepcopy(table)
                project["updatedAt"] = now_iso()

            mutate_technical_gap_project(project_id, apply)
        except Exception:
            logger.exception("项目 %s 素材匹配后自动构建事实表失败，可在事实表页手动刷新", project_id)

    async def gaps(self, project_id: str, request: Request) -> dict[str, Any]:
        try:
            url_scope = self._url_scope(request)

            # 读接口顺带自愈：命中修复才落库，且走 CAS，避免盖掉后台填写刚写入的产物
            def apply(project: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
                gap_state = ensure_technical_gap_state(project)
                repaired = repair_technical_gap_state_fill_task_skills(gap_state)
                plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
                decisions_changed = recompute_technical_gap_decisions(plan) if plan else 0
                changed = bool(repaired or decisions_changed)
                if changed:
                    self._refresh_gap_integrity(project, gap_state)
                    gap_state["items"] = legacy_technical_gap_items_from_plan(plan)
                    project["updatedAt"] = now_iso()
                return changed, self._gap_filling_payload(project_id, project, gap_state, **url_scope)

            _, payload = mutate_technical_gap_project(
                project_id, apply, persist_when=lambda outcome: outcome[0]
            )
            return payload
        except Exception as exc:
            _raise_gap_error(exc, "Gap plan not found")

    async def update_gap(self, project_id: str, gap_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            def apply(project: dict[str, Any]) -> dict[str, Any]:
                gap_state = ensure_technical_gap_state(project)
                if gap_state["recognitionStatus"] != "completed":
                    raise ValueError("请先完成缺口识别。")

                item = find_technical_gap_item(gap_state, gap_id)
                plan_item = find_technical_gap_plan_item(gap_state, gap_id)
                payload = data or {}
                action = str(payload.get("action") or payload.get("status") or "").strip()
                if action in {"skip", "skipped"}:
                    item["status"] = "skipped"
                    item["skipReason"] = str(payload.get("reason") or item.get("skipReason") or "未填写原因")
                    item["resolvedSource"] = ""
                    item["resolvedAt"] = ""
                    if plan_item is not None:
                        plan_item["status"] = "ignored"
                        plan_item["skipReason"] = item["skipReason"]
                        plan_item["reviewNotes"] = list(plan_item.get("reviewNotes") or []) + [
                            f"人工忽略：{item['skipReason']}"
                        ]
                elif action in {"resolve", "resolved"}:
                    source = payload.get("source") or {}
                    source_name = str(source.get("name") or "") if isinstance(source, dict) else str(source)
                    item["status"] = "resolved"
                    item["resolvedSource"] = (
                        source_name.strip()
                        or str(payload.get("resolvedSource") or item.get("resolvedSource") or "已补录")
                    )
                    item["skipReason"] = ""
                    item["resolvedAt"] = now_iso()
                    if plan_item is not None:
                        plan_item["status"] = "resolved"
                        plan_item["resolvedSource"] = item["resolvedSource"]
                        plan_item["resolvedAt"] = item["resolvedAt"]
                        plan_item.setdefault("resolvedArtifacts", []).append(
                            {
                                "id": f"ART-{gap_id}-{len(plan_item.get('resolvedArtifacts') or []) + 1}",
                                "source": "manual",
                                "fileName": item["resolvedSource"],
                                "createdAt": item["resolvedAt"],
                                "s7Ready": True,
                            }
                        )
                elif action in {"checking", "pending"}:
                    item["status"] = action
                    if plan_item is not None:
                        plan_item["status"] = "filling" if action == "checking" else "needs_input"
                else:
                    raise ValueError("不支持的缺口状态更新。")

                gap_state["submittedForReview"] = False
                gap_state["reviewConfirmed"] = False
                gap_state["reviewedAt"] = ""
                self._refresh_gap_integrity(project, gap_state)
                project["review_document_state"] = default_technical_review_document_state(project)
                return {
                    "message": "缺口状态已更新",
                    "item": copy.deepcopy(item),
                    "payload": self._gap_filling_payload(project_id, project, gap_state),
                }

            return mutate_technical_gap_project(project_id, apply)
        except Exception as exc:
            _raise_gap_error(exc, "Gap not found")

    def upload_material(
        self,
        project_id: str,
        gap_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            url_scope = self._url_scope(request)

            def apply(project: dict[str, Any]) -> dict[str, Any]:
                gap_state = ensure_technical_gap_state(project)
                if gap_state["recognitionStatus"] != "completed":
                    raise ValueError("请先完成缺口识别。")
                # 落 docx 的目标路径由 gapId + 标题决定，重放会覆盖同名文件，幂等
                result = register_technical_manual_gap_upload(project, gap_id, data or {}, **url_scope)
                self._refresh_gap_integrity(project, ensure_technical_gap_state(project))
                return copy.deepcopy(result)

            return mutate_technical_gap_project(project_id, apply)
        except Exception as exc:
            _raise_gap_error(exc, "Gap not found")

    async def artifact_content(self, project_id: str, artifact_id: str, filename: str = "") -> FileResponse:
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
            artifact = None
            for item in plan.get("items") or []:
                for candidate in item.get("resolvedArtifacts") or []:
                    if str(candidate.get("id") or "") == artifact_id:
                        artifact = copy.deepcopy(candidate)
                        break
                if artifact is not None:
                    break
            if artifact is None:
                raise KeyError(artifact_id)
        except Exception as exc:
            _raise_gap_error(exc, "Gap artifact not found")
        path = Path(str(artifact.get("path") or ""))
        if not path.exists():
            raise HTTPException(status_code=404, detail="缺口附件不存在或已被删除。")
        _ = filename
        return FileResponse(path=path, filename=str(artifact.get("fileName") or path.name))

    async def artifact_callback(
        self,
        project_id: str,
        artifact_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
    ) -> JSONResponse:
        payload = data or {}
        _validate_callback_token(request)

        status = int(payload.get("status") or 0)
        if status not in {2, 6} or not payload.get("url"):
            return JSONResponse({"error": 0})

        callback_version: int | None = None
        callback_version_raw = request.query_params.get("oo_doc_version")
        if callback_version_raw:
            try:
                callback_version = int(callback_version_raw)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="OnlyOffice 编辑会话版本无效。") from exc

        downloaded_path: Path | None = None
        try:
            project = require_technical_gap_project_for_update(project_id)
            artifact = _find_gap_artifact(project, artifact_id)
            _validate_editable_gap_artifact(artifact, callback_version)
            download_url = _validate_download_url(str(payload["url"]))
            target_path = Path(str(artifact.get("path") or ""))
            if not target_path.exists():
                raise ValueError("缺口产物文件不存在或已被删除。")

            with tempfile.NamedTemporaryFile(
                dir=target_path.parent,
                prefix=f".{target_path.name}.callback-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                downloaded_path = Path(handle.name)
            try:
                await download_document_from_onlyoffice(
                    download_url,
                    downloaded_path,
                    max_bytes=settings.onlyoffice_download_max_bytes,
                )
            except (httpx.HTTPError, RuntimeError) as exc:
                return JSONResponse(status_code=502, content={"error": 1, "message": str(exc)})

            edited_at = now_iso()
            edited_by = str(
                request.query_params.get("operator")
                or payload.get("operator")
                or "当前用户"
            )
            with _artifact_callback_lock(project_id, artifact_id):
                latest = require_technical_gap_project_for_update(project_id)
                latest_artifact = _find_gap_artifact(latest, artifact_id)
                current_version = _validate_editable_gap_artifact(latest_artifact, callback_version)
                latest_target_path = Path(str(latest_artifact.get("path") or ""))
                if latest_target_path.resolve() != target_path.resolve():
                    raise _StaleArtifactSession("产物文件已被替换。")
                if not latest_target_path.exists():
                    raise ValueError("缺口产物文件不存在或已被删除。")

                with tempfile.NamedTemporaryFile(
                    dir=latest_target_path.parent,
                    prefix=f".{latest_target_path.name}.backup-",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    backup_path = Path(handle.name)
                backup_path.unlink(missing_ok=True)
                latest_target_path.replace(backup_path)
                downloaded_path.replace(latest_target_path)
                try:
                    def apply(project: dict[str, Any]) -> None:
                        target = _find_gap_artifact(project, artifact_id)
                        session_version = _validate_editable_gap_artifact(target, callback_version)
                        if Path(str(target.get("path") or "")).resolve() != latest_target_path.resolve():
                            raise _StaleArtifactSession("产物文件已被替换。")
                        target["ooDocVersion"] = session_version + 1 if status == 2 else session_version
                        target["ooContentRevision"] = int(target.get("ooContentRevision") or 0) + 1
                        target["editedAt"] = edited_at
                        target["editedBy"] = edited_by
                        target["lastOnlyOfficeStatus"] = status
                        project["updatedAt"] = edited_at

                    mutate_technical_gap_project(project_id, apply)
                except Exception:
                    latest_target_path.unlink(missing_ok=True)
                    backup_path.replace(latest_target_path)
                    raise
                else:
                    backup_path.unlink(missing_ok=True)
            return JSONResponse({"error": 0})
        except _StaleArtifactSession:
            return JSONResponse({"error": 0, "ignored": "stale_document_version"})
        except Exception as exc:
            _raise_gap_error(exc, "Gap artifact not found")
        finally:
            if downloaded_path is not None:
                downloaded_path.unlink(missing_ok=True)

    def confirm_ai_fill_artifact(
        self,
        project_id: str,
        gap_id: str,
        artifact_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            def apply(project: dict[str, Any]) -> dict[str, Any]:
                gap_state = ensure_technical_gap_state(project)
                plan_item = find_technical_gap_plan_item(gap_state, gap_id)
                if plan_item is None:
                    raise KeyError(gap_id)
                artifacts = [
                    artifact
                    for artifact in (plan_item.get("resolvedArtifacts") or [])
                    if isinstance(artifact, dict)
                ]
                target = next(
                    (artifact for artifact in artifacts if str(artifact.get("id") or "") == artifact_id), None
                )
                if target is None or str(target.get("source") or "") != "ai_fill":
                    raise KeyError(artifact_id)
                if target.get("supersededAt") or target.get("active", True) is False:
                    raise ValueError("该 AI 填写产物已被新的选材或填写结果取代，不能再复核通过。")

                fill_task_id = str(target.get("fillTaskId") or "")
                batch_artifacts = [
                    artifact
                    for artifact in artifacts
                    if str(artifact.get("source") or "") == "ai_fill"
                    and not artifact.get("supersededAt")
                    and artifact.get("active", True) is not False
                    and (
                        str(artifact.get("fillTaskId") or "") == fill_task_id
                        if fill_task_id
                        else str(artifact.get("id") or "") == artifact_id
                    )
                ]
                confirmed_at = now_iso()
                confirmed_by = str((data or {}).get("operator") or "当前用户")
                for artifact in batch_artifacts:
                    artifact["s7Ready"] = True
                    artifact["active"] = True
                    artifact.pop("revokedAt", None)
                    artifact.pop("revokedBy", None)
                    artifact["qualityGate"] = "human_confirmed"
                    artifact["confirmed"] = True
                    artifact["confirmedAt"] = confirmed_at
                    artifact["confirmedBy"] = confirmed_by

                # 审核归属具体 fillTask（R10-B07-02）：目录项级 qualityStatus 只在全部填写任务
                # 完成、且所有 AI 填写产物均已放行后才收口为 human_confirmed；否则保留填写阶段
                # 的质检状态，避免前端把仍有待填/待审任务的目录项整体误判为「已就绪」。
                pending_fill_tasks = [
                    task
                    for task in (plan_item.get("fillTasks") or [])
                    if isinstance(task, dict) and str(task.get("status") or "pending") != "completed"
                ]
                unready_ai_artifacts = [
                    artifact
                    for artifact in artifacts
                    if str(artifact.get("source") or "") == "ai_fill"
                    and not technical_gap_artifact_is_s7_ready(artifact)
                ]
                if not pending_fill_tasks and not unready_ai_artifacts:
                    plan_item["qualityStatus"] = "human_confirmed"
                plan_item.setdefault("reviewNotes", []).append(
                    f"人工确认 AI 填写产物可用于合并：{len(batch_artifacts)} 份"
                )
                gap_state["submittedForReview"] = False
                gap_state["reviewConfirmed"] = False
                gap_state["reviewedAt"] = ""
                self._refresh_gap_integrity(project, gap_state)
                gap_state["items"] = legacy_technical_gap_items_from_plan(gap_state.get("plan") or {})
                project["review_document_state"] = default_technical_review_document_state(project)
                return {
                    "message": f"已确认 {len(batch_artifacts)} 份 AI 填写产物可用于合并。",
                    "item": copy.deepcopy(plan_item),
                    "artifact": copy.deepcopy(target),
                    "artifacts": copy.deepcopy(batch_artifacts),
                    "gapPlan": copy.deepcopy(gap_state.get("plan") or {}),
                }

            return mutate_technical_gap_project(project_id, apply)
        except Exception as exc:
            _raise_gap_error(exc, "Gap artifact not found")

    def confirm_ready(
        self,
        project_id: str,
        gap_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 目录节点「确认」（产品裁决 2026-07-21）：除文件名精确命中自动就绪外，目录项变
        # 「已就绪」的唯一途径是人工点确认；确认无前置条件，以人的判断为准，可撤销。
        # 只落 humanConfirmed 人工背书标记，不改写 decision/status 终审结果。
        try:
            def apply(project: dict[str, Any]) -> dict[str, Any]:
                gap_state = ensure_technical_gap_state(project)
                if gap_state["recognitionStatus"] != "completed":
                    raise ValueError("请先完成缺口识别。")
                plan_item = find_technical_gap_plan_item(gap_state, gap_id)
                if plan_item is None:
                    raise KeyError(gap_id)
                payload = data or {}
                confirmed = payload.get("confirmed", True) is not False
                operator = str(payload.get("operator") or "当前用户")
                timestamp = now_iso()
                plan_item["humanConfirmed"] = confirmed
                plan_item["humanConfirmedAt"] = timestamp if confirmed else ""
                plan_item["humanConfirmedBy"] = operator if confirmed else ""
                artifacts = [
                    artifact
                    for artifact in (plan_item.get("resolvedArtifacts") or [])
                    if isinstance(artifact, dict)
                ]
                if confirmed:
                    # 重新确认只恢复上次撤销停用的产物；已被新选材/上传取代的（supersededAt）不恢复。
                    for artifact in artifacts:
                        if artifact.get("supersededAt") or "revokedAt" not in artifact:
                            continue
                        artifact.pop("revokedAt", None)
                        artifact.pop("revokedBy", None)
                        artifact["s7Ready"] = True
                        artifact["active"] = True
                else:
                    # 撤销定案必须同时停用当前产物：保留在 resolvedArtifacts 里作审计历史，
                    # 但 s7Ready/active 置否，S7 装配不再消费被撤销的素材。
                    for artifact in artifacts:
                        if artifact.get("s7Ready", True) is False:
                            continue
                        artifact["s7Ready"] = False
                        artifact["active"] = False
                        artifact["revokedAt"] = timestamp
                        artifact["revokedBy"] = operator
                    if str(plan_item.get("qualityStatus") or "") == "human_confirmed":
                        plan_item["qualityStatus"] = ""
                plan_item.setdefault("reviewNotes", []).append(
                    f"人工确认已就绪：{operator}" if confirmed else f"撤销就绪确认：{operator}"
                )
                self._refresh_gap_integrity(project, gap_state)
                gap_state["items"] = legacy_technical_gap_items_from_plan(gap_state.get("plan") or {})
                return {
                    "message": "本章已人工确认就绪。" if confirmed else "已撤销本章的就绪确认。",
                    "item": copy.deepcopy(plan_item),
                    "gapPlan": copy.deepcopy(gap_state.get("plan") or {}),
                }

            return mutate_technical_gap_project(project_id, apply)
        except Exception as exc:
            _raise_gap_error(exc, "Gap not found")

    def set_title_only(
        self,
        project_id: str,
        gap_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 目录节点「忽略」（S3 树状改造 2026-08-04）：本级仅保留标题骨架，不再匹配素材，
        # 内容下放子级各自匹配；可取消。只落 titleOnly 标记，冻结/释放由前端按树派生。
        try:
            def apply(project: dict[str, Any]) -> dict[str, Any]:
                gap_state = ensure_technical_gap_state(project)
                if gap_state["recognitionStatus"] != "completed":
                    raise ValueError("请先完成缺口识别。")
                plan_item = find_technical_gap_plan_item(gap_state, gap_id)
                if plan_item is None:
                    raise KeyError(gap_id)
                payload = data or {}
                enabled = payload.get("enabled", True) is not False
                operator = str(payload.get("operator") or "当前用户")
                timestamp = now_iso()
                plan_item["titleOnly"] = enabled
                plan_item["titleOnlyAt"] = timestamp if enabled else ""
                plan_item["titleOnlyBy"] = operator if enabled else ""
                plan_item.setdefault("reviewNotes", []).append(
                    f"人工忽略本级（仅保留标题）：{operator}" if enabled else f"取消忽略本级：{operator}"
                )
                self._refresh_gap_integrity(project, gap_state)
                gap_state["items"] = legacy_technical_gap_items_from_plan(gap_state.get("plan") or {})
                return {
                    "message": "本级已忽略，仅保留标题，子级将各自匹配素材。" if enabled else "已取消忽略本级。",
                    "item": copy.deepcopy(plan_item),
                    "gapPlan": copy.deepcopy(gap_state.get("plan") or {}),
                }

            return mutate_technical_gap_project(project_id, apply)
        except Exception as exc:
            _raise_gap_error(exc, "Gap not found")

    async def select_material(
        self,
        project_id: str,
        gap_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prepared_files: list[dict[str, Any]] = []
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            if gap_state["recognitionStatus"] != "completed":
                raise ValueError("请先完成缺口识别。")
            # 素材下载要走 MinIO 取原始 Word，读到写之间有数秒敞口；下载完再原子写入，
            # 否则这期间后台填写写入的产物会被这次整份覆盖掉。
            prepared_files = await prepare_technical_existing_gap_material_files(project, gap_id, data or {})
            url_scope = self._url_scope(request)

            def apply(latest: dict[str, Any]) -> dict[str, Any]:
                # 失败回滚由 mutate_technical_gap_project 统一负责（含落库失败）
                result = register_technical_existing_gap_material(
                    latest,
                    gap_id,
                    data or {},
                    prepared_files,
                    **url_scope,
                )
                self._refresh_gap_integrity(latest, ensure_technical_gap_state(latest))
                return copy.deepcopy(result)

            return mutate_technical_gap_project(project_id, apply)
        except Exception as exc:
            recovery_errors: list[Exception] = []
            if prepared_files:
                try:
                    cleanup_prepared_technical_gap_material_files(prepared_files)
                except Exception as cleanup_error:
                    recovery_errors.append(cleanup_error)
            if recovery_errors:
                exc = ExceptionGroup("选择素材失败，且事务回滚未能完整完成。", [exc, *recovery_errors])
            _raise_gap_error(exc, "Gap not found")

    async def submit_review(self, project_id: str) -> dict[str, Any]:
        try:
            def apply(project: dict[str, Any]) -> dict[str, Any]:
                gap_state = ensure_technical_gap_state(project)
                if gap_state["recognitionStatus"] != "completed":
                    raise ValueError("请先完成缺口识别后再提交确认。")

                plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
                recompute_technical_gap_decisions(plan)
                gap_state["items"] = legacy_technical_gap_items_from_plan(plan)
                integrity = check_technical_gap_integrity(plan)
                gap_state["integrity"] = integrity
                if integrity["status"] != "passed":
                    raise ValueError(f"仍有 {integrity['blockingCount']} 项缺口未解决，暂不可提交审核。")

                gap_state["submittedForReview"] = True
                gap_state["reviewConfirmed"] = False
                gap_state["reviewedAt"] = ""
                project["updatedAt"] = now_iso()
                return {
                    "message": "缺口处理已通过完整性校验并提交审核。",
                    "payload": self._gap_filling_payload(project_id, project, gap_state),
                }

            return mutate_technical_gap_project(project_id, apply)
        except Exception as exc:
            _raise_gap_error(exc, "Gap review not found")

    async def facts(self, project_id: str) -> dict[str, Any]:
        project = require_technical_gap_project_for_update(project_id)
        gap_state = ensure_technical_gap_state(project)
        specs, specs_ref = resolve_fact_specs()
        table = gap_state.get("projectFactTable") if isinstance(gap_state.get("projectFactTable"), dict) else {}
        if table.get("schemaVersion") == PROJECT_FACT_TABLE_SCHEMA_VERSION:
            payload = copy.deepcopy(table)
        else:
            payload = empty_project_fact_table(project_id)
        # 全局清单是否已上传：前端据此决定空态引导（去规则页）还是展示字段
        payload["specsImported"] = bool(specs)
        payload["specsFileName"] = str(specs_ref.get("fileName") or "")
        payload["specTotal"] = len(specs)
        # 规则版本元数据：审计当前生效的是哪一版全局清单
        payload["specsRuleId"] = str(specs_ref.get("ruleId") or "")
        payload["specsVersion"] = int(specs_ref.get("version") or 0)
        payload["specsSha256"] = str(specs_ref.get("sha256") or "")
        # 用户自定义的参考资料目录（素材库虚拟路径），事实表匹配时并入扫描
        custom_paths = gap_state.get("factMaterialPaths") if isinstance(gap_state.get("factMaterialPaths"), list) else []
        payload["materialPaths"] = [str(path) for path in custom_paths if str(path or "").strip()]
        # 默认生效的素材范围：与 AI 匹配填充实际扫描的三层口径一致，供前端如实展示
        payload["materialScopes"] = default_fact_material_scopes(project)
        # 附表来源矩阵绑定状态：按客户读取（规则按客户维护，项目套用所属客户那份）
        payload["appendixSourceMatrix"] = await self._appendix_source_matrix_meta_for_project(project)
        return payload

    async def _appendix_source_matrix_meta_for_project(self, project: dict[str, Any]) -> dict[str, Any]:
        """项目所属客户的附表规则元数据；无规则或身份解析失败返回空 dict。"""
        try:
            identity = build_project_identity(project)
        except Exception:
            return {}
        customer_id = str(identity.get("customerId") or "")
        if not customer_id:
            return {}
        from app.services.technical_rules_store import appendix_rules_meta

        meta = await appendix_rules_meta(customer_id)
        if not meta:
            return {}
        return {
            **meta,
            "customerName": str(identity.get("customerCanonicalName") or identity.get("customerName") or ""),
        }

    async def save_fact_material_sources(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """保存本项目的参考资料目录：素材库虚拟路径列表（如 技术标/项目定制/其他项目）。

        事实表匹配默认只扫「项目定制/本项目」目录；这里配置的路径会并入扫描，
        用于用户自行指定相关项目目录作为参考来源。
        """
        raw_paths = data.get("paths") if isinstance(data, dict) else None
        if not isinstance(raw_paths, list):
            raise HTTPException(status_code=400, detail="paths 必须是字符串数组。")
        paths: list[str] = []
        for raw in raw_paths:
            path = str(raw or "").strip().strip("/")
            # 容错：用户常省略标类前缀（如 项目定制/xxx），统一补全为素材库完整路径
            if path and not path.startswith(f"{TECHNICAL_BID_TYPE}/"):
                path = f"{TECHNICAL_BID_TYPE}/{path}"
            if path and path not in paths:
                paths.append(path)

        def apply(project: dict[str, Any]) -> None:
            gap_state = ensure_technical_gap_state(project)
            gap_state["factMaterialPaths"] = paths
            project["updatedAt"] = now_iso()

        mutate_technical_gap_project(project_id, apply)
        return {"paths": paths}

    async def fetch_fact_material(self, project_id: str, material_id: str) -> dict[str, Any]:
        """按需把事实表候选素材物化到工作区，返回本地可读路径。

        幂等：已落地的直接复用缓存，不重复下载。构造 curate manifest 时只给素材清单，
        skill 判断要读哪几份后经本接口现取，避免为清单里的每份素材全量下载。
        """
        material_id = str(material_id or "").strip()
        if not material_id:
            raise HTTPException(status_code=400, detail="素材 ID 不能为空。")
        project = require_technical_gap_project_for_update(project_id)
        work_dir = project_fact_material_work_dir(project)
        cache_dir = work_dir / "material_index"
        cached = project_fact_material_cached_path(cache_dir, material_id)
        if cached is not None:
            return {"materialId": material_id, "path": str(cached), "cached": True}
        work_dir.mkdir(parents=True, exist_ok=True)
        # 下载内部经 run_awaitable_sync 桥接异步，与 build_facts 同一模式放工作线程
        prepared = await asyncio.to_thread(
            materialize_project_fact_material,
            {"id": material_id},
            work_dir,
            bid_type=TECHNICAL_BID_TYPE,
        )
        path = str(prepared.get("path") or "")
        if not path or not Path(path).is_file():
            raise HTTPException(status_code=404, detail=f"素材 {material_id} 取不到可读文件。")
        return {"materialId": material_id, "path": path, "cached": False}

    async def upload_appendix_source_matrix(
        self, project_id: str, filename: str, content: bytes
    ) -> dict[str, Any]:
        """项目级附表来源矩阵上传（《填写文件来源》Excel：客户 × 附表 → 项目定制/标准文件/其他来源）。

        规则已改为按客户维护：本端点保留兼容（项目不存在 404、xlsx 留盘、绑定元数据），
        同时把文件中属于本项目客户的规则行透写到客户规则库（全量替换该客户规则），
        消费链统一从客户规则库读取，项目级文件不再独立生效。
        """
        if not filename.lower().endswith((".xlsx", ".xlsm")):
            raise HTTPException(status_code=400, detail="附表填写规则必须是 .xlsx 文件。")
        if not content:
            raise HTTPException(status_code=400, detail="上传文件为空。")
        tmp_upload: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
                handle.write(content)
                tmp_upload = Path(handle.name)
            matrix = parse_appendix_source_matrix(tmp_upload)
        finally:
            if tmp_upload is not None:
                tmp_upload.unlink(missing_ok=True)
        rows = matrix.get("rows") if isinstance(matrix.get("rows"), list) else []
        if not rows:
            raise HTTPException(
                status_code=400,
                detail="未解析到有效规则行，请检查表头（客户/表格/项目定制/标准文件/其他）。",
            )

        snapshot = require_technical_gap_project_for_update(project_id)
        identity = build_project_identity(snapshot)
        customer_id = str(identity.get("customerId") or "")
        customer_name = str(identity.get("customerCanonicalName") or identity.get("customerName") or "")
        own_rows = [
            row
            for row in rows
            if customer_id
            and str(canonical_customer(row.get("customer")).get("customerId") or "") == customer_id
        ]

        target_dir = settings.documents_dir / project_id / "technical-workspace"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "appendix-source-matrix.xlsx"
        target_path.write_bytes(content)
        uploaded_at = now_iso()

        def bind_matrix(project: dict[str, Any]) -> None:
            project["technicalAppendixSourceMatrix"] = {
                "path": str(target_path),
                "fileName": filename,
                "rowCount": len(rows),
                "uploadedAt": uploaded_at,
            }
            project["updatedAt"] = uploaded_at

        mutate_technical_gap_project(project_id, bind_matrix)
        # 透写客户规则库：只取属于本项目客户的行，全量替换该客户规则
        if own_rows:
            await replace_appendix_rules(
                customer_id, customer_name, own_rows, "项目级上传", file_name=filename
            )
        applied = await self._apply_appendix_source_matrix_to_plan(project_id)
        return {
            "fileName": filename,
            "rowCount": len(own_rows) if own_rows else len(rows),
            "uploadedAt": uploaded_at,
            "applied": applied,
        }

    async def _apply_appendix_source_matrix_to_plan(self, project_id: str) -> dict[str, int]:
        """上传/重传矩阵后，把规则直接应用到已生成的 gap plan（不重跑整个缺口识别）。

        交互顺序是「先素材匹配、后传规则」，因此识别完成的 plan 需要在原地补上
        sourceRouting 与规则推荐素材；尚无 plan 时返回空 dict，规则留待识别时生效。
        """
        snapshot = require_technical_gap_project_for_update(project_id)
        gap_state = ensure_technical_gap_state(snapshot)
        plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
        if gap_state.get("recognitionStatus") != "completed" or not plan.get("items"):
            return {}
        from app.services.technical_gap_planner import _allowed_technical_material_index

        # 规则按客户维护：项目套用所属客户的规则库（SQL 为唯一事实来源）
        identity = build_project_identity(snapshot)
        matrix = await load_appendix_matrix_for_customer(
            str(identity.get("customerCanonicalName") or identity.get("customerName") or "")
        )
        material_scope = build_project_material_scope(snapshot)
        turbine_model = project_turbine_model(snapshot)
        # 素材索引构建内部经 run_awaitable_sync 桥接，与 build_facts 同模式放工作线程
        materials = await asyncio.to_thread(_allowed_technical_material_index, material_scope, turbine_model, gap_state)
        customer_name = str(
            snapshot.get("customerName")
            or (snapshot.get("identity") or {}).get("customerName")
            or (snapshot.get("identity") or {}).get("owner")
            or ""
        )
        stats: dict[str, int] = {}

        # 索引构建是重活，跑完再把规则套到最新 plan 上：重放只重跑套规则本身
        def apply(project: dict[str, Any]) -> bool:
            nonlocal stats
            latest_state = ensure_technical_gap_state(project)
            latest_plan = latest_state.get("plan") if isinstance(latest_state.get("plan"), dict) else {}
            if latest_state.get("recognitionStatus") != "completed" or not latest_plan.get("items"):
                stats = {}
                return False
            stats = apply_appendix_source_matrix_to_plan(
                latest_plan, matrix, customer_name=customer_name, materials=materials
            )
            # 新增路由或清除旧路由都算改动：第二版规则零命中时 routedItems 为 0，
            # 但旧矩阵路由已被清除，不持久化会让旧路由在重新读取时复活（R10-B09-03）。
            changed = bool(stats.get("routedItems") or stats.get("clearedItems") or stats.get("clearedTasks"))
            if changed:
                project["updatedAt"] = now_iso()
            return changed

        mutate_technical_gap_project(project_id, apply, persist_when=lambda changed: changed)
        return stats

    async def replay_appendix_source_matrix_for_customer(self, customer_name: str) -> dict[str, Any]:
        """客户规则保存/导入后，重放到该客户名下「缺口识别已完成」的技术标项目。

        按 build_project_identity 匹配项目清单逐个重放，单项目失败不阻塞其他项目。
        """
        customer_id = str(canonical_customer(customer_name).get("customerId") or "")
        summary: dict[str, Any] = {"replayed": 0, "failed": 0, "projects": []}
        if not customer_id:
            return summary
        from app.services.store import store

        listing = store.list_projects(bid_type=TECHNICAL_BID_TYPE, page=1, page_size=10000)
        for item in listing.get("items") or []:
            project_id = str(item.get("id") or "") if isinstance(item, dict) else ""
            if not project_id:
                continue
            try:
                project = get_technical_gap_project_runtime_state(project_id)
                identity = build_project_identity(project)
                if str(identity.get("customerId") or "") != customer_id:
                    continue
                gap_state = ensure_technical_gap_state(project)
                if gap_state.get("recognitionStatus") != "completed":
                    continue
                stats = await self._apply_appendix_source_matrix_to_plan(project_id)
                summary["replayed"] += 1
                summary["projects"].append({"projectId": project_id, "applied": stats})
            except Exception as exc:  # 单项目失败不阻塞其他项目
                summary["failed"] += 1
                summary["projects"].append({"projectId": project_id, "error": str(exc)})
        return summary


    async def build_facts(self, project_id: str) -> dict[str, Any]:
        try:
            snapshot = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(snapshot)
            if gap_state["recognitionStatus"] != "completed":
                raise ValueError("请先完成缺口识别，再维护项目事实表。")
            specs, _ = resolve_fact_specs()
            if not specs:
                raise ValueError("尚未上传事实表清单，请先到素材库 · 规则页上传后再生成。")
            # 同步构建放到工作线程：内部素材查询经 run_awaitable_sync 桥接异步，
            # 在事件循环线程内直接调用会被拒并降级为空素材（字段全部 unextracted）。
            # 构建是重活，跑完再原子写回，重放只重放赋值。
            table = await asyncio.to_thread(build_project_fact_table, snapshot, gap_state)

            def apply(project: dict[str, Any]) -> None:
                ensure_technical_gap_state(project)["projectFactTable"] = copy.deepcopy(table)
                project["updatedAt"] = now_iso()

            mutate_technical_gap_project(project_id, apply)
            return copy.deepcopy(table)
        except Exception as exc:
            _raise_gap_error(exc, "Gap facts not found")

    async def material_check(self, project_id: str) -> dict[str, Any]:
        """素材齐备性预检：按清单 referenceFile 类别对账本项目素材，缺失类别给跨项目候选。"""
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            # 同步重活（素材索引/全库扫描内部经 run_awaitable_sync 桥接）放工作线程，
            # 与 build_facts 同一模式，不在事件循环线程内直接跑
            return await asyncio.to_thread(build_fact_material_check, project, gap_state)
        except Exception as exc:
            _raise_gap_error(exc, "Gap facts not found")

    async def save_facts(self, project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            snapshot = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(snapshot)
            if gap_state["recognitionStatus"] != "completed":
                raise ValueError("请先完成缺口识别，再维护项目事实表。")
            payload = data or {}
            current = gap_state.get("projectFactTable")
            if not isinstance(current, dict) or current.get("schemaVersion") != PROJECT_FACT_TABLE_SCHEMA_VERSION:
                current = await asyncio.to_thread(build_project_fact_table, snapshot, gap_state)
            specs, specs_ref = resolve_fact_specs()
            incoming_fields = payload.get("fields") if isinstance(payload.get("fields"), list) else current.get("fields") or []
            confirm = bool(payload.get("confirm") or payload.get("confirmed"))
            operator = str(payload.get("operator") or "当前用户")
            saved_at = now_iso()
            # 整表 confirm 只把表级 status 升为 confirmed（正文填写的准入闸门），
            # 不逐字段盖成"已人工确认"——字段级确认只由 PATCH 单字段接口产生。
            # 否则一次保存就把 148 个字段全变成 AI 禁区，AI 自己填错的值再也纠正不了。
            fields = [
                normalize_project_fact_field(field, index=index, confirm=False, operator=operator, saved_at=saved_at)
                for index, field in enumerate(incoming_fields, start=1)
                if isinstance(field, dict)
            ]
            table = {
                "schemaVersion": PROJECT_FACT_TABLE_SCHEMA_VERSION,
                "projectId": project_id,
                "status": "confirmed" if confirm else "draft",
                "builtAt": str(current.get("builtAt") or saved_at),
                "updatedAt": saved_at,
                "confirmedAt": saved_at if confirm else str(current.get("confirmedAt") or ""),
                "confirmedBy": operator if confirm else str(current.get("confirmedBy") or ""),
                "fields": fields,
                "summary": summarize_project_fact_fields(fields, spec_total=len(specs)),
                "factSpecsRef": copy.deepcopy(current.get("factSpecsRef"))
                if isinstance(current.get("factSpecsRef"), dict)
                else copy.deepcopy(specs_ref),
            }
            def apply(project: dict[str, Any]) -> None:
                ensure_technical_gap_state(project)["projectFactTable"] = copy.deepcopy(table)
                project["updatedAt"] = saved_at

            mutate_technical_gap_project(project_id, apply)
            return copy.deepcopy(table)
        except Exception as exc:
            _raise_gap_error(exc, "Gap facts not found")

    async def curate_facts(self, project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """提交 AI 匹配填充任务：立即返回，执行交给后台 worker，进度经 curate_status 轮询。

        单轮 curate 要跑几分钟，同步返回会把连接占满整轮且关页面就丢结果；任务化后
        弹窗关闭、页面刷新都不影响执行，状态持久化在 gap_state["factCurateState"]。
        """
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            if gap_state["recognitionStatus"] != "completed":
                raise ValueError("请先完成缺口识别，再维护项目事实表。")
            table = gap_state.get("projectFactTable")
            if not isinstance(table, dict) or table.get("schemaVersion") != PROJECT_FACT_TABLE_SCHEMA_VERSION:
                table = await asyncio.to_thread(build_project_fact_table, project, gap_state)

                def store_table(latest: dict[str, Any]) -> None:
                    ensure_technical_gap_state(latest)["projectFactTable"] = copy.deepcopy(table)
                    latest["updatedAt"] = now_iso()

                mutate_technical_gap_project(project_id, store_table)
            if fact_curate_running(gap_state) or fact_curate_locked(project_id):
                raise HTTPException(status_code=409, detail="AI 匹配填充正在进行中，请等待本轮完成。")
            state = await asyncio.to_thread(schedule_fact_curate_job, project_id, data or {})
            return {
                "factCurateState": state,
                "message": "已提交 AI 匹配填充任务，可关闭弹窗，任务在后台继续。",
            }
        except Exception as exc:
            _raise_gap_error(exc, "Gap facts not found")

    async def curate_status(self, project_id: str) -> dict[str, Any]:
        """AI 匹配填充状态：终态时一并带上最新事实表与报告，前端一次拿全。"""
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            state = fact_curate_state(gap_state)
            payload: dict[str, Any] = {"factCurateState": state}
            if str(state.get("status") or "") in {"succeeded", "failed"}:
                table = gap_state.get("projectFactTable")
                if isinstance(table, dict):
                    payload["projectFactTable"] = copy.deepcopy(table)
                report = state.get("report")
                if isinstance(report, dict):
                    payload["curateReport"] = copy.deepcopy(report)
                payload["message"] = str(state.get("message") or "")
            return payload
        except Exception as exc:
            _raise_gap_error(exc, "Gap facts not found")

    async def recheck(self, project_id: str) -> dict[str, Any]:
        try:
            def apply(project: dict[str, Any]) -> dict[str, Any]:
                gap_state = ensure_technical_gap_state(project)
                if gap_state["recognitionStatus"] != "completed":
                    raise ValueError("请先完成缺口识别。")
                plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
                recompute_technical_gap_decisions(plan)
                gap_state["items"] = legacy_technical_gap_items_from_plan(plan)
                integrity = check_technical_gap_integrity(plan)
                gap_state["integrity"] = integrity
                if isinstance(gap_state.get("plan"), dict):
                    gap_state["plan"]["integrity"] = integrity
                    gap_state["plan"]["summary"] = summarize_technical_gap_plan(gap_state["plan"])
                project["updatedAt"] = now_iso()
                return {
                    "message": "缺口完整性校验完成。",
                    "integrity": copy.deepcopy(integrity),
                }

            return mutate_technical_gap_project(project_id, apply)
        except Exception as exc:
            _raise_gap_error(exc, "Gap plan not found")

    def ai_fill(
        self,
        project_id: str,
        gap_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        slot: tuple[str, str] | None = None
        try:
            # 与一键填写同一模式：在快照上跑完，再把这条目录项原子并回最新状态
            snapshot = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(snapshot)
            if gap_state["recognitionStatus"] != "completed":
                raise ValueError("请先完成缺口识别。")
            _require_no_body_fill_running(project_id, gap_state)
            slot = _acquire_ai_fill_slot(project_id, gap_id)
            if slot is None:
                raise PeripheralError(409, "该目录项正在 AI 填写中，请等待完成后再试。", "AI_FILL_RUNNING")
            repair_technical_gap_state_fill_task_skills(gap_state)
            self._require_confirmed_project_fact_table(gap_state)
            result = run_technical_ai_fill_for_gap(snapshot, gap_id, data or {}, **self._url_scope(request))
            filled_item = plan_item_snapshot(snapshot, gap_id)
            filled_task_id = str(
                (result.get("artifact") or {}).get("fillTaskId") or (data or {}).get("fillTaskId") or ""
            )

            def apply(project: dict[str, Any]) -> dict[str, Any]:
                latest_state = ensure_technical_gap_state(project)
                repair_technical_gap_state_fill_task_skills(latest_state)
                apply_filled_gap_item(project, gap_id, filled_item, fill_task_id=filled_task_id)
                final_state = ensure_technical_gap_state(project)
                self._refresh_gap_integrity(project, final_state)
                # 终审（recompute_technical_gap_decisions）跑在落库这份状态上，
                # 返回值要取终审后的结果，否则前端拿到的 decision 还停在填写前。
                return {
                    "item": plan_item_snapshot(project, gap_id),
                    "gapPlan": copy.deepcopy(final_state.get("plan") or {}),
                }

            final = mutate_technical_gap_project(project_id, apply)
            payload = copy.deepcopy(result)
            payload["item"] = final["item"]
            payload["gapPlan"] = final["gapPlan"]
            return payload
        except Exception as exc:
            _raise_gap_error(exc, "Gap not found")
        finally:
            if slot is not None:
                _release_ai_fill_slot(project_id, gap_id, slot)

    def body_fill_all(self, project_id: str, request: Request, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """一键填写（正文 + 附表）：提交后台任务后立即返回，进度走 bodyFillState 轮询。"""
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            if gap_state["recognitionStatus"] != "completed":
                raise ValueError("请先完成缺口识别。")
            if repair_technical_gap_state_fill_task_skills(gap_state):
                self._persist_fill_task_skill_repair(project_id)
            self._require_confirmed_project_fact_table(gap_state)
            # 僵尸状态（worker 被重启/杀掉，状态停在 running 但队列锁已释放）不挡新任务，
            # 否则前端永远显示「填写中」，只能改库才能恢复
            if body_fill_running(gap_state) and not body_fill_stale(gap_state, project_id):
                raise PeripheralError(409, "一键填写任务正在执行，请等待完成后再提交。", "BODY_FILL_RUNNING")
            payload = dict(data or {})
            targets = collect_body_fill_targets(gap_state, payload)
            if not targets:
                skips = collect_body_fill_skips(gap_state, payload)
                if skips:
                    raise ValueError(
                        f"当前范围内没有可自动填写的任务：{len(skips)} 条附表任务按来源规则待补资料，请先补充素材。"
                    )
                raise ValueError("当前范围内没有待填写的正文或附表任务。")
            payload["expectedTotal"] = len(targets)
            payload.update(
                {
                    "browserBaseUrl": self._url_scope(request)["browser_base_url"],
                    "onlyofficeBaseUrl": self._url_scope(request)["onlyoffice_base_url"],
                }
            )
            state = schedule_body_fill_job(project_id, payload)
            return {"bodyFillState": state, "total": len(targets)}
        except Exception as exc:
            _raise_gap_error(exc, "项目不存在")
            raise

    def body_fill_status(self, project_id: str) -> dict[str, Any]:
        project = self.ensure_project(project_id)
        gap_state = ensure_technical_gap_state(project)
        state = body_fill_state(gap_state)
        if body_fill_stale(gap_state, project_id):
            state["status"] = "failed"
            state["message"] = "任务执行中断（服务重启或进程退出），请重新发起一键填写。"
        return {
            "bodyFillState": state,
            "pendingTotal": len(collect_body_fill_targets(gap_state, {})),
            "gapPlan": copy.deepcopy(gap_state.get("plan") or {}),
        }


technical_gap_service = TechnicalGapService()
