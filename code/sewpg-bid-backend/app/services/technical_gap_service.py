from __future__ import annotations

import asyncio
import copy
import tempfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from app.core.config import settings
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.identity import build_project_material_scope
from app.services.material_folder_scope import project_material_root_path
from app.services.technical_appendix_source_matrix import (
    apply_appendix_source_matrix_to_plan,
    load_appendix_source_matrix_for_project,
    parse_appendix_source_matrix,
)
from app.services.turbine_models import project_turbine_model
from app.services.technical_gap_fact_table import (
    FACT_STATUS_CONFIRMED,
    FACT_STATUS_MISSING_SOURCE,
    FACT_STATUS_NOT_APPLICABLE,
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
from app.services.bid_runtime_state import now_iso
from app.services.technical_gap_actions import (
    TECHNICAL_TABLE_FILL_SKILL_NAME,
    TECHNICAL_WORD_FILL_SKILL_NAME,
    apply_technical_gap_parent_coverage,
    build_technical_gap_plan_for_project,
    cleanup_prepared_technical_gap_material_files,
    prepare_technical_existing_gap_material_files,
    register_technical_existing_gap_material,
    register_technical_manual_gap_upload,
    run_technical_ai_fill_for_gap,
)
from app.services.technical_gap_domain import (
    aggregate_technical_gap_fill_quality,
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
from app.services.technical_fact_material_classes import build_fact_material_check
from app.services.technical_fact_spec_import import FactSpecImportError, import_specs
from app.services.technical_fact_spec_versions import fact_specs_ref, save_fact_spec_version
from app.services.technical_gap_repository import (
    get_technical_gap_project_runtime_state,
    persist_technical_gap_project,
    require_technical_gap_project_for_update,
)
from app.services.technical_gap_state import (
    default_technical_review_document_state,
    ensure_technical_gap_state,
    legacy_technical_gap_items_from_plan,
    repair_technical_gap_state_fill_task_skills,
)
from app.services.url_utils import onlyoffice_backend_base_url


PROJECT_FACT_CONFIRMED_STATUSES = {"confirmed"}


def appendix_source_matrix_meta(project: dict[str, Any]) -> dict[str, Any]:
    """项目级附表来源矩阵元数据：无绑定时返回空 dict，前端据此切换按钮空态/已上传态。"""
    raw = project.get("technicalAppendixSourceMatrix")
    if not isinstance(raw, dict):
        raw = {}
    path = str(
        raw.get("path")
        or project.get("technicalAppendixSourceMatrixPath")
        or project.get("appendixSourceMatrixPath")
        or ""
    ).strip()
    if not path:
        return {}
    return {
        "path": path,
        "fileName": str(raw.get("fileName") or ""),
        "rowCount": int(raw.get("rowCount") or 0),
        "uploadedAt": str(raw.get("uploadedAt") or ""),
    }

# 逐字段确认的终态集合：全部字段进入终态后表级 status 自动升 confirmed
PROJECT_FACT_FIELD_TERMINAL_STATUSES = {
    FACT_STATUS_CONFIRMED,
    FACT_STATUS_NOT_APPLICABLE,
    FACT_STATUS_MISSING_SOURCE,
}


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


def _raise_gap_error(exc: Exception, not_found_detail: str) -> None:
    contract_error = exc
    while isinstance(contract_error, ExceptionGroup) and contract_error.exceptions:
        first_error = contract_error.exceptions[0]
        if not isinstance(first_error, Exception):
            break
        contract_error = first_error
    if isinstance(contract_error, PeripheralError):
        raise HTTPException(status_code=contract_error.status_code, detail=contract_error.detail) from exc
    if isinstance(contract_error, (RuntimeError, ValueError)):
        raise HTTPException(status_code=400, detail=str(contract_error)) from exc
    if isinstance(contract_error, KeyError):
        raise HTTPException(status_code=404, detail=not_found_detail) from exc
    raise exc


class TechnicalGapService:
    def ensure_project(self, project_id: str) -> dict[str, Any]:
        return get_technical_gap_project_runtime_state(project_id)

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
        if gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先触发缺口识别后再进入缺口处理。")
        repaired = repair_technical_gap_state_fill_task_skills(gap_state)
        plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
        decisions_changed = recompute_technical_gap_decisions(plan) if plan else 0
        if repaired or decisions_changed:
            self._refresh_gap_integrity(project, gap_state)
            gap_state["items"] = legacy_technical_gap_items_from_plan(plan)
            project["updatedAt"] = now_iso()
            persist_technical_gap_project(project)
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

    async def detection_status(self, project_id: str) -> dict[str, Any]:
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            repaired = repair_technical_gap_state_fill_task_skills(gap_state)
            plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
            decisions_changed = recompute_technical_gap_decisions(plan) if plan else 0
            if repaired or decisions_changed:
                self._refresh_gap_integrity(project, gap_state)
                gap_state["items"] = legacy_technical_gap_items_from_plan(plan)
                project["updatedAt"] = now_iso()
                persist_technical_gap_project(project)
            return build_technical_gap_detection_payload(project, gap_state)
        except Exception as exc:
            _raise_gap_error(exc, "Gap detection not found")

    def run_detection(self, project_id: str) -> dict[str, Any]:
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            plan = build_technical_gap_plan_for_project(project)
            items = legacy_technical_gap_items_from_plan(plan)
            recognized_at = now_iso()
            plan["summary"] = summarize_technical_gap_plan(plan)
            plan["integrity"] = {}
            gap_state.update(
                {
                    "recognitionStatus": "completed",
                    "recognizedAt": recognized_at,
                    "submittedForReview": False,
                    "reviewConfirmed": False,
                    "reviewedAt": "",
                    "items": items,
                    "plan": plan,
                    "planFile": str(plan.get("planFile") or ""),
                    "integrity": {},
                }
            )
            project["review_document_state"] = default_technical_review_document_state(project)
            project["updatedAt"] = recognized_at
            persist_technical_gap_project(project)
            payload = build_technical_gap_detection_payload(project, gap_state)
        except Exception as exc:
            _raise_gap_error(exc, "Gap detection not found")
        return {
            **payload,
            "message": f"缺口识别完成，共识别 {payload['summary']['totalTocItems']} 个目录项。",
        }

    async def gaps(self, project_id: str, request: Request) -> dict[str, Any]:
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            return self._gap_filling_payload(project_id, project, gap_state, **self._url_scope(request))
        except Exception as exc:
            _raise_gap_error(exc, "Gap plan not found")

    async def update_gap(self, project_id: str, gap_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            project = require_technical_gap_project_for_update(project_id)
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
                    source_name.strip() or str(payload.get("resolvedSource") or item.get("resolvedSource") or "已补录")
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
            persist_technical_gap_project(project)
            return {
                "message": "缺口状态已更新",
                "item": copy.deepcopy(item),
                "payload": self._gap_filling_payload(project_id, project, gap_state),
            }
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
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            if gap_state["recognitionStatus"] != "completed":
                raise ValueError("请先完成缺口识别。")
            result = register_technical_manual_gap_upload(project, gap_id, data or {}, **self._url_scope(request))
            gap_state = ensure_technical_gap_state(project)
            self._refresh_gap_integrity(project, gap_state)
            persist_technical_gap_project(project)
            return copy.deepcopy(result)
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

    def confirm_ai_fill_artifact(
        self,
        project_id: str,
        gap_id: str,
        artifact_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            plan_item = find_technical_gap_plan_item(gap_state, gap_id)
            if plan_item is None:
                raise KeyError(gap_id)
            artifacts = [
                artifact
                for artifact in (plan_item.get("resolvedArtifacts") or [])
                if isinstance(artifact, dict)
            ]
            target = next((artifact for artifact in artifacts if str(artifact.get("id") or "") == artifact_id), None)
            if target is None or str(target.get("source") or "") != "ai_fill":
                raise KeyError(artifact_id)

            fill_task_id = str(target.get("fillTaskId") or "")
            batch_artifacts = [
                artifact
                for artifact in artifacts
                if str(artifact.get("source") or "") == "ai_fill"
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
            persist_technical_gap_project(project)
            return {
                "message": f"已确认 {len(batch_artifacts)} 份 AI 填写产物可用于合并。",
                "item": copy.deepcopy(plan_item),
                "artifact": copy.deepcopy(target),
                "artifacts": copy.deepcopy(batch_artifacts),
                "gapPlan": copy.deepcopy(gap_state.get("plan") or {}),
            }
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
            project = require_technical_gap_project_for_update(project_id)
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
            plan_item.setdefault("reviewNotes", []).append(
                f"人工确认已就绪：{operator}" if confirmed else f"撤销就绪确认：{operator}"
            )
            self._refresh_gap_integrity(project, gap_state)
            gap_state["items"] = legacy_technical_gap_items_from_plan(gap_state.get("plan") or {})
            persist_technical_gap_project(project)
            return {
                "message": "本章已人工确认就绪。" if confirmed else "已撤销本章的就绪确认。",
                "item": copy.deepcopy(plan_item),
                "gapPlan": copy.deepcopy(gap_state.get("plan") or {}),
            }
        except Exception as exc:
            _raise_gap_error(exc, "Gap not found")

    def set_parent_coverage(
        self,
        project_id: str,
        gap_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 人工设「父章节覆盖」（产品需求 2026-07-27）：以本节点为覆盖源，把其后代目录项
        # 统一标成 covered_by_parent；人工已单独选过素材的子节跳过，可撤销。
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            if gap_state["recognitionStatus"] != "completed":
                raise ValueError("请先完成缺口识别。")
            result = apply_technical_gap_parent_coverage(project, gap_id, data or {})
            self._refresh_gap_integrity(project, gap_state)
            gap_state["items"] = legacy_technical_gap_items_from_plan(gap_state.get("plan") or {})
            persist_technical_gap_project(project)
            covered = (data or {}).get("covered", True) is not False
            applied = result.get("applied") or []
            skipped = result.get("skipped") or []
            action = "已设为父章节覆盖" if covered else "已撤销父章节覆盖"
            message = f"{action}：{len(applied)} 个下级目录项"
            if skipped:
                reason = "已自行选用素材" if covered else "非人工设置"
                message += f"，跳过 {len(skipped)} 个（{reason}）"
            return {
                "message": f"{message}。",
                "item": copy.deepcopy(result.get("item") or {}),
                "applied": applied,
                "skipped": skipped,
                "gapPlan": copy.deepcopy(gap_state.get("plan") or {}),
            }
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
            project = require_technical_gap_project_for_update(project_id)
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
            persist_technical_gap_project(project)
            return {
                "message": "本级已忽略，仅保留标题，子级将各自匹配素材。" if enabled else "已取消忽略本级。",
                "item": copy.deepcopy(plan_item),
                "gapPlan": copy.deepcopy(gap_state.get("plan") or {}),
            }
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
        project: dict[str, Any] | None = None
        project_snapshot: dict[str, Any] | None = None
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            if gap_state["recognitionStatus"] != "completed":
                raise ValueError("请先完成缺口识别。")
            project_snapshot = copy.deepcopy(project)
            prepared_files = await prepare_technical_existing_gap_material_files(project, gap_id, data or {})
            result = register_technical_existing_gap_material(
                project,
                gap_id,
                data or {},
                prepared_files,
                **self._url_scope(request),
            )
            gap_state = ensure_technical_gap_state(project)
            self._refresh_gap_integrity(project, gap_state)
            persist_technical_gap_project(project)
            return copy.deepcopy(result)
        except Exception as exc:
            recovery_errors: list[Exception] = []
            if project is not None and project_snapshot is not None:
                try:
                    project.clear()
                    project.update(project_snapshot)
                except Exception as rollback_error:
                    recovery_errors.append(rollback_error)
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
            project = require_technical_gap_project_for_update(project_id)
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
            persist_technical_gap_project(project)
            return {
                "message": "缺口处理已通过完整性校验并提交审核。",
                "payload": self._gap_filling_payload(project_id, project, gap_state),
            }
        except Exception as exc:
            _raise_gap_error(exc, "Gap review not found")

    async def facts(self, project_id: str) -> dict[str, Any]:
        project = require_technical_gap_project_for_update(project_id)
        gap_state = ensure_technical_gap_state(project)
        fact_specs = gap_state.get("factSpecs") if isinstance(gap_state.get("factSpecs"), dict) else {}
        specs = fact_specs.get("specs") if isinstance(fact_specs.get("specs"), list) else []
        table = gap_state.get("projectFactTable") if isinstance(gap_state.get("projectFactTable"), dict) else {}
        if table.get("schemaVersion") == PROJECT_FACT_TABLE_SCHEMA_VERSION:
            payload = copy.deepcopy(table)
        else:
            payload = empty_project_fact_table(project_id)
        # 项目级事实表上传状态：前端据此决定空态引导还是展示字段
        payload["specsImported"] = bool(specs)
        payload["specsFileName"] = str(fact_specs.get("fileName") or "")
        payload["specTotal"] = len(specs)
        # 规则版本元数据（R06-B04-02）：审计当前绑定的是哪一版规则
        payload["specsRuleId"] = str(fact_specs.get("ruleId") or "")
        payload["specsVersion"] = int(fact_specs.get("version") or 0)
        payload["specsSha256"] = str(fact_specs.get("sha256") or "")
        # 用户自定义的参考资料目录（素材库虚拟路径），事实表匹配时并入扫描
        custom_paths = gap_state.get("factMaterialPaths") if isinstance(gap_state.get("factMaterialPaths"), list) else []
        payload["materialPaths"] = [str(path) for path in custom_paths if str(path or "").strip()]
        # 默认生效的素材范围：与 AI 匹配填充实际扫描的三层口径一致，供前端如实展示
        payload["materialScopes"] = default_fact_material_scopes(project)
        # 附表来源矩阵绑定状态：前端「附表填写规则」按钮的空态/已上传态
        payload["appendixSourceMatrix"] = appendix_source_matrix_meta(project)
        return payload

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

        project = require_technical_gap_project_for_update(project_id)
        gap_state = ensure_technical_gap_state(project)
        gap_state["factMaterialPaths"] = paths
        project["updatedAt"] = now_iso()
        persist_technical_gap_project(project)
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

        绑定到 project["technicalAppendixSourceMatrix"]，resolve_appendix_source_matrix_path
        以该路径为最高优先级，下次缺口识别时经 manifest 传给 gap-planner 定 sourceRouting。
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

        project = require_technical_gap_project_for_update(project_id)
        target_dir = settings.documents_dir / project_id / "technical-workspace"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "appendix-source-matrix.xlsx"
        target_path.write_bytes(content)
        uploaded_at = now_iso()
        project["technicalAppendixSourceMatrix"] = {
            "path": str(target_path),
            "fileName": filename,
            "rowCount": len(rows),
            "uploadedAt": uploaded_at,
        }
        project["updatedAt"] = uploaded_at
        persist_technical_gap_project(project)
        applied = await self._apply_appendix_source_matrix_to_plan(project)
        return {
            "fileName": filename,
            "rowCount": len(rows),
            "uploadedAt": uploaded_at,
            "applied": applied,
        }

    async def _apply_appendix_source_matrix_to_plan(self, project: dict[str, Any]) -> dict[str, int]:
        """上传/重传矩阵后，把规则直接应用到已生成的 gap plan（不重跑整个缺口识别）。

        交互顺序是「先素材匹配、后传规则」，因此识别完成的 plan 需要在原地补上
        sourceRouting 与规则推荐素材；尚无 plan 时返回空 dict，规则留待识别时生效。
        """
        gap_state = ensure_technical_gap_state(project)
        plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
        if gap_state.get("recognitionStatus") != "completed" or not plan.get("items"):
            return {}
        from app.services.technical_gap_planner import _allowed_technical_material_index

        matrix = load_appendix_source_matrix_for_project(project)
        material_scope = build_project_material_scope(project)
        turbine_model = project_turbine_model(project)
        # 素材索引构建内部经 run_awaitable_sync 桥接，与 build_facts 同模式放工作线程
        materials = await asyncio.to_thread(_allowed_technical_material_index, material_scope, turbine_model, gap_state)
        customer_name = str(
            project.get("customerName")
            or (project.get("identity") or {}).get("customerName")
            or (project.get("identity") or {}).get("owner")
            or ""
        )
        stats = apply_appendix_source_matrix_to_plan(plan, matrix, customer_name=customer_name, materials=materials)
        # 新增路由或清除旧路由都算改动：第二版规则零命中时 routedItems 为 0，
        # 但旧矩阵路由已被清除，不持久化会让旧路由在重新读取时复活（R10-B09-03）。
        if stats.get("routedItems") or stats.get("clearedItems") or stats.get("clearedTasks"):
            project["updatedAt"] = now_iso()
            persist_technical_gap_project(project)
        return stats

    async def upload_fact_specs(
        self, project_id: str, filename: str, content: bytes, operator: str = "当前用户"
    ) -> dict[str, Any]:
        """项目级事实表 Excel 上传：固化为不可变规则版本并绑定到本项目（R06-B04-02）。

        每次上传生成独立版本（ruleId/版本号/上传人/时间/sha256 落数据卷），
        gap_state["factSpecs"] 只更新本项目的绑定与 specs 快照，不影响其他项目。
        """
        if not filename.lower().endswith(".xlsx"):
            raise HTTPException(status_code=400, detail="事实表必须是 .xlsx 文件。")
        if not content:
            raise HTTPException(status_code=400, detail="上传文件为空。")
        tmp_upload: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
                handle.write(content)
                tmp_upload = Path(handle.name)
            specs = import_specs(tmp_upload)
        except FactSpecImportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            if tmp_upload is not None:
                tmp_upload.unlink(missing_ok=True)

        project = require_technical_gap_project_for_update(project_id)
        gap_state = ensure_technical_gap_state(project)
        previous = gap_state.get("factSpecs") if isinstance(gap_state.get("factSpecs"), dict) else {}
        binding = save_fact_spec_version(
            project_id,
            specs,
            file_name=filename,
            uploaded_by=operator,
            content=content,
            previous_version=int(previous.get("version") or 0),
        )
        gap_state["factSpecs"] = binding
        project["updatedAt"] = binding["uploadedAt"]
        persist_technical_gap_project(project)
        ref = fact_specs_ref(binding)
        return {
            "specTotal": len(specs),
            "fileName": filename,
            "uploadedAt": binding["uploadedAt"],
            "ruleId": ref["ruleId"],
            "version": ref["version"],
            "sha256": ref["sha256"],
        }

    async def build_facts(self, project_id: str) -> dict[str, Any]:
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            if gap_state["recognitionStatus"] != "completed":
                raise ValueError("请先完成缺口识别，再维护项目事实表。")
            fact_specs = gap_state.get("factSpecs") if isinstance(gap_state.get("factSpecs"), dict) else {}
            if not fact_specs.get("specs"):
                raise ValueError("请先上传本项目的事实表 Excel，再生成项目事实表。")
            # 同步构建放到工作线程：内部素材查询经 run_awaitable_sync 桥接异步，
            # 在事件循环线程内直接调用会被拒并降级为空素材（字段全部 unextracted）。
            table = await asyncio.to_thread(build_project_fact_table, project, gap_state)
            gap_state["projectFactTable"] = table
            project["updatedAt"] = now_iso()
            persist_technical_gap_project(project)
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
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            if gap_state["recognitionStatus"] != "completed":
                raise ValueError("请先完成缺口识别，再维护项目事实表。")
            payload = data or {}
            current = gap_state.get("projectFactTable")
            if not isinstance(current, dict) or current.get("schemaVersion") != PROJECT_FACT_TABLE_SCHEMA_VERSION:
                current = await asyncio.to_thread(build_project_fact_table, project, gap_state)
            fact_specs = gap_state.get("factSpecs") if isinstance(gap_state.get("factSpecs"), dict) else {}
            specs = fact_specs.get("specs") if isinstance(fact_specs.get("specs"), list) else []
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
                else fact_specs_ref(fact_specs),
            }
            gap_state["projectFactTable"] = table
            project["updatedAt"] = saved_at
            persist_technical_gap_project(project)
            return copy.deepcopy(table)
        except Exception as exc:
            _raise_gap_error(exc, "Gap facts not found")

    async def save_fact_field(
        self,
        project_id: str,
        field_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            if gap_state["recognitionStatus"] != "completed":
                raise ValueError("请先完成缺口识别，再维护项目事实表。")
            table = gap_state.get("projectFactTable")
            if not isinstance(table, dict) or table.get("schemaVersion") != PROJECT_FACT_TABLE_SCHEMA_VERSION:
                raise KeyError(field_id)
            fields = [field for field in (table.get("fields") or []) if isinstance(field, dict)]
            # 字段定位与前端行 key 一致：优先 id（build 时生成的 FACT-XXXX），其次 key
            target_index = next(
                (
                    index
                    for index, field in enumerate(fields)
                    if str(field.get("id") or "") == str(field_id)
                    or str(field.get("key") or "") == str(field_id)
                ),
                None,
            )
            if target_index is None:
                raise KeyError(field_id)
            payload = data or {}
            confirm = bool(payload.get("confirm", True))
            operator = str(payload.get("operator") or "当前用户")
            saved_at = now_iso()
            merged = copy.deepcopy(fields[target_index])
            if "value" in payload:
                merged["value"] = str(payload.get("value") or "")
            if "status" in payload:
                merged["status"] = str(payload.get("status") or "")
            normalized = normalize_project_fact_field(
                merged,
                index=target_index + 1,
                confirm=confirm,
                operator=operator,
                saved_at=saved_at,
            )
            fields[target_index] = normalized
            fact_specs = gap_state.get("factSpecs") if isinstance(gap_state.get("factSpecs"), dict) else {}
            specs = fact_specs.get("specs") if isinstance(fact_specs.get("specs"), list) else []
            summary = summarize_project_fact_fields(fields, spec_total=len(specs))
            all_terminal = bool(fields) and all(
                str(field.get("status") or "") in PROJECT_FACT_FIELD_TERMINAL_STATUSES for field in fields
            )
            status = str(table.get("status") or "draft")
            confirmed_at = str(table.get("confirmedAt") or "")
            confirmed_by = str(table.get("confirmedBy") or "")
            if all_terminal:
                status = "confirmed"
                confirmed_at = confirmed_at or saved_at
                confirmed_by = operator
            table = {
                **table,
                "status": status,
                "updatedAt": saved_at,
                "confirmedAt": confirmed_at,
                "confirmedBy": confirmed_by,
                "fields": fields,
                "summary": summary,
            }
            gap_state["projectFactTable"] = table
            project["updatedAt"] = saved_at
            persist_technical_gap_project(project)
            return {
                "field": copy.deepcopy(normalized),
                "summary": copy.deepcopy(summary),
                "status": status,
            }
        except Exception as exc:
            _raise_gap_error(exc, "Gap fact field not found")

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
                gap_state["projectFactTable"] = table
                project["updatedAt"] = now_iso()
                persist_technical_gap_project(project)
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
            project = require_technical_gap_project_for_update(project_id)
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
            persist_technical_gap_project(project)
            return {
                "message": "缺口完整性校验完成。",
                "integrity": copy.deepcopy(integrity),
            }
        except Exception as exc:
            _raise_gap_error(exc, "Gap plan not found")

    def ai_fill(
        self,
        project_id: str,
        gap_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            if gap_state["recognitionStatus"] != "completed":
                raise ValueError("请先完成缺口识别。")
            if repair_technical_gap_state_fill_task_skills(gap_state):
                project["updatedAt"] = now_iso()
                persist_technical_gap_project(project)
            self._require_confirmed_project_fact_table(gap_state)
            result = run_technical_ai_fill_for_gap(project, gap_id, data or {}, **self._url_scope(request))
            gap_state = ensure_technical_gap_state(project)
            self._refresh_gap_integrity(project, gap_state)
            persist_technical_gap_project(project)
            return copy.deepcopy(result)
        except Exception as exc:
            _raise_gap_error(exc, "Gap not found")

    def ai_fill_all(self, project_id: str, request: Request, data: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            if gap_state["recognitionStatus"] != "completed":
                raise ValueError("请先完成缺口识别。")
            if repair_technical_gap_state_fill_task_skills(gap_state):
                project["updatedAt"] = now_iso()
                persist_technical_gap_project(project)
            self._require_confirmed_project_fact_table(gap_state)
            plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
            payload = data or {}
            requested_gap_ids = {
                str(item or "").strip()
                for item in (payload.get("gapIds") if isinstance(payload.get("gapIds"), list) else [])
                if str(item or "").strip()
            }
            tasks: list[tuple[int, int, int, str, str]] = []
            for index, item in enumerate(plan.get("items") or [], start=1):
                if not isinstance(item, dict):
                    continue
                gap_id = str(item.get("id") or "")
                if requested_gap_ids and gap_id not in requested_gap_ids:
                    continue
                if str(item.get("decision") or "") != "fill_required":
                    continue
                for task_index, task in enumerate(item.get("fillTasks") or [], start=1):
                    if not isinstance(task, dict):
                        continue
                    if str(task.get("status") or "pending") == "completed" and not payload.get("rerun"):
                        continue
                    skill = str(task.get("skill") or TECHNICAL_TABLE_FILL_SKILL_NAME)
                    rank = 0 if skill == TECHNICAL_WORD_FILL_SKILL_NAME else 1
                    tasks.append((rank, index, task_index, gap_id, str(task.get("id") or "")))
            tasks.sort(key=lambda item: (item[0], item[1], item[2]))
            base_data = {key: value for key, value in payload.items() if key not in {"fillTaskId", "gapIds", "rerun"}}
            results: list[dict[str, Any]] = []
            errors: list[dict[str, str]] = []
            for _, _, _, gap_id, fill_task_id in tasks:
                try:
                    result = run_technical_ai_fill_for_gap(
                        project,
                        gap_id,
                        {**base_data, "fillTaskId": fill_task_id, "operator": str(payload.get("operator") or "当前用户")},
                        **self._url_scope(request),
                    )
                    artifact = result.get("artifact") if isinstance(result.get("artifact"), dict) else {}
                    artifacts = [
                        item
                        for item in (result.get("artifacts") if isinstance(result.get("artifacts"), list) else [artifact])
                        if isinstance(item, dict) and item
                    ]
                    for artifact_item in artifacts:
                        results.append(
                            {
                                "gapId": gap_id,
                                "artifactId": str(artifact_item.get("id") or ""),
                                "artifactIds": [
                                    str(item.get("id") or "") for item in artifacts if str(item.get("id") or "")
                                ],
                                "skill": str(artifact_item.get("skill") or ""),
                                "fileName": str(artifact_item.get("fileName") or ""),
                                "batchTargetIndex": artifact_item.get("batchTargetIndex") or 0,
                                "batchTargetCount": artifact_item.get("batchTargetCount") or 0,
                                "qualityReport": copy.deepcopy(artifact_item.get("qualityReport") or {}),
                            }
                        )
                    project["updatedAt"] = now_iso()
                    persist_technical_gap_project(project)
                except Exception as exc:  # pragma: no cover - batch must report failures instead of hiding progress
                    errors.append({"gapId": gap_id, "message": str(exc)})
            gap_state = ensure_technical_gap_state(project)
            self._refresh_gap_integrity(project, gap_state)
            persist_technical_gap_project(project)
            aggregate = aggregate_technical_gap_fill_quality(results, errors)
            return {
                "status": "completed" if not errors else "needs_review",
                "summary": {
                    "total": len(results) + len(errors),
                    "passed": sum(1 for result in results if result.get("qualityReport", {}).get("status") == "passed"),
                    "needsReview": sum(
                        1 for result in results if result.get("qualityReport", {}).get("status") != "passed"
                    ),
                    "failed": len(errors),
                },
                "qualityReport": aggregate,
                "results": results,
                "errors": errors,
                "gapPlan": copy.deepcopy(gap_state.get("plan") or {}),
                "projectFactTable": copy.deepcopy(gap_state.get("projectFactTable") or {}),
            }
        except Exception as exc:
            _raise_gap_error(exc, "Gap plan not found")

    async def submissions(self, project_id: str) -> dict[str, Any]:
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            submissions = copy.deepcopy(gap_state["submissions"])
            return {"items": submissions, "total": len(submissions)}
        except Exception as exc:
            _raise_gap_error(exc, "Gap submissions not found")

    async def submit_material(self, project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            project = require_technical_gap_project_for_update(project_id)
            gap_state = ensure_technical_gap_state(project)
            if gap_state["recognitionStatus"] != "completed":
                raise ValueError("请先完成缺口识别。")

            payload = data or {}
            missing_id = str(payload.get("missingId") or "").strip()
            files = list(payload.get("files") or [])
            if not missing_id:
                raise ValueError("missingId 不能为空。")
            if not files:
                raise ValueError("至少需要提交一个文件。")

            item = find_technical_gap_item(gap_state, missing_id)
            receipts: list[dict[str, Any]] = []
            timestamp = now_iso()
            for index, file in enumerate(files, start=1):
                file_name = str(file.get("name") or f"{missing_id}-{index}.docx").strip() or f"{missing_id}-{index}.docx"
                receipt = {
                    "receiptId": f"mr-{project_id}-{len(gap_state['submissions']) + index}",
                    "projectId": project_id,
                    "missingId": missing_id,
                    "fileId": f"raw-{project_id}-{len(gap_state['submissions']) + index}",
                    "fileName": file_name,
                    "storedPath": project_material_root_path(TECHNICAL_BID_TYPE, project_id),
                    "action": "upload",
                    "operator": str(payload.get("operator") or "当前用户"),
                    "submittedAt": timestamp,
                    "traceId": f"mock-{project_id}-{len(gap_state['submissions']) + index}",
                    "auditId": f"audit-{project_id}-{len(gap_state['submissions']) + index}",
                }
                receipts.append(receipt)

            gap_state["submissions"] = receipts + list(gap_state["submissions"])
            item["latestUploadAt"] = timestamp
            item["latestSubmissionId"] = receipts[0]["receiptId"]
            if item["status"] != "resolved":
                item["status"] = "checking"
            plan_item = find_technical_gap_plan_item(gap_state, missing_id)
            if plan_item is not None:
                plan_item["status"] = "filling"
                plan_item["latestUploadAt"] = timestamp
                plan_item["latestSubmissionId"] = receipts[0]["receiptId"]
                plan_item.setdefault("resolvedArtifacts", []).extend(
                    {
                        "id": receipt["receiptId"],
                        "source": "manual_upload",
                        "fileName": receipt["fileName"],
                        "path": receipt["storedPath"],
                        "createdAt": receipt["submittedAt"],
                        "s7Ready": False,
                    }
                    for receipt in receipts
                )
                if isinstance(gap_state.get("plan"), dict):
                    gap_state["plan"]["summary"] = summarize_technical_gap_plan(gap_state["plan"])
                    gap_state["integrity"] = check_technical_gap_integrity(gap_state["plan"])
                    gap_state["plan"]["integrity"] = gap_state["integrity"]
            gap_state["submittedForReview"] = False
            gap_state["reviewConfirmed"] = False
            gap_state["reviewedAt"] = ""
            project["review_document_state"] = default_technical_review_document_state(project)
            project["updatedAt"] = timestamp
            persist_technical_gap_project(project)
            return {
                "message": f"补料提交成功，共 {len(receipts)} 个文件。",
                "item": copy.deepcopy(item),
                "receipts": receipts,
                "payload": self._gap_filling_payload(project_id, project, gap_state),
                "traceId": receipts[0]["traceId"],
            }
        except Exception as exc:
            _raise_gap_error(exc, "Gap not found")

    async def patch_missing(
        self,
        project_id: str,
        missing_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return await self.update_gap(project_id, missing_id, data or {})
        except Exception as exc:
            _raise_gap_error(exc, "Gap not found")


technical_gap_service = TechnicalGapService()
