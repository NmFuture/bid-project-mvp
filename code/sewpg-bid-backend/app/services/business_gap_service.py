from __future__ import annotations

import asyncio
import base64
import copy
import json
import mimetypes
import shutil
from pathlib import Path
from typing import Any

from fastapi import Request

from app.services.bid_type import BUSINESS_BID_TYPE, require_bid_type
from app.services.business_gap_planning import (
    build_business_gap_plan_for_project,
    build_business_gap_material_picker_index,
    refresh_business_gap_artifact_urls,
    run_business_table_fill_skill,
    summarize_business_gap_plan,
)
from app.services.business_gap_refresh import (
    refresh_material_kind_labels,
    refresh_template_candidates,
)
from app.services.business_gap_domain import (
    apply_task_artifact_intent,
    assembly_mode_for_artifact,
    decode_upload_content,
    default_material_target_path,
    default_task_assembly_mode,
    find_artifact_in_task,
    find_task,
    find_toc_ref,
    material_usage_for_assembly_mode,
    merge_material_refs,
    recompute_task_after_artifact_change,
    selected_material_entries,
    selected_template_entry,
    table_fill_target,
    task_can_ai_draft,
    task_fill_plan,
    update_toc_ref_statuses,
    unique_path,
)
from app.services.business_gap_fact_table import (
    PROJECT_FACT_TABLE_SCHEMA_VERSION,
    build_project_fact_table,
    empty_project_fact_table,
    fact_table_value_map,
    normalize_business_fact_fields_for_save,
    normalize_project_fact_field,
    summarize_project_fact_fields,
)
from app.services.business_gap_table_fill import (
    business_table_fill_source_materials,
    prepare_business_table_fill_sources,
    prepare_business_table_fill_target,
)
from app.services.business_s1_handoff import business_s1_consumption_context
from app.services.business_gap_state import (
    ensure_business_gap_state,
    finalize_business_gap_plan_update,
    record_business_gap_detection_result,
    record_business_material_feedback,
)
from app.services.business_gap_repository import (
    get_business_gap_project_runtime_state,
    persist_business_gap_project,
    require_business_gap_project_for_update,
)
from app.services.business_gap_ai_draft import write_business_ai_draft_docx
from app.services.business_material_store import business_material_store
from app.services.bid_runtime_state import now_iso
from app.services.file_utils import safe_filename
from app.services.material_folder_scope import project_material_root_path
from app.services.minio_client import minio_client
from app.services.performance_library_service import performance_library_service
from app.services.url_utils import onlyoffice_backend_base_url
from app.services.workspace_artifacts import business_workspace_dir


class BusinessGapService:
    def ensure_project(self, project_id: str) -> dict[str, Any]:
        return get_business_gap_project_runtime_state(project_id)

    def _project_for_update(self, project_id: str) -> dict[str, Any]:
        return require_business_gap_project_for_update(project_id)

    def _browser_base_url(self, request: Request) -> str:
        return str(request.base_url).rstrip("/")

    def _onlyoffice_base_url(self, request: Request) -> str:
        return onlyoffice_backend_base_url(request)

    def _url_scope(self, request: Request) -> dict[str, str]:
        return {
            "browser_base_url": self._browser_base_url(request),
            "onlyoffice_base_url": self._onlyoffice_base_url(request),
        }

    @staticmethod
    def _refresh_plan_urls(project_id: str, plan: dict[str, Any], url_scope: dict[str, str]) -> None:
        refresh_business_gap_artifact_urls(project_id, plan, **url_scope)

    @staticmethod
    def _finalize_plan_update(
        project: dict[str, Any],
        business_gap_state: dict[str, Any],
        plan: dict[str, Any],
        *,
        updated_at: str,
    ) -> None:
        finalize_business_gap_plan_update(project, business_gap_state, plan, updated_at=updated_at)
        persist_business_gap_project(project)

    def _gap_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        return {
            **payload,
            "message": f"商务标缺口计划生成完成，共 {summary.get('taskCount', 0)} 个任务。",
        }

    @staticmethod
    def _preview_renderer(file_name: str, mime_type: str) -> str:
        suffix = Path(str(file_name or "")).suffix.lower()
        lowered_mime = str(mime_type or "").lower()
        if lowered_mime.startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
            return "image"
        if lowered_mime == "application/pdf" or suffix == ".pdf":
            return "pdf"
        if suffix in {".doc", ".docx"} or "word" in lowered_mime:
            return "word"
        if suffix in {".xls", ".xlsx"} or "spreadsheet" in lowered_mime or "excel" in lowered_mime:
            return "spreadsheet"
        if suffix in {".ppt", ".pptx"} or "presentation" in lowered_mime or "powerpoint" in lowered_mime:
            return "presentation"
        return "download"

    @staticmethod
    def _onlyoffice_document_type(file_name: str, renderer: str) -> str:
        suffix = Path(str(file_name or "")).suffix.lower()
        if renderer == "spreadsheet" or suffix in {".xls", ".xlsx", ".csv"}:
            return "cell"
        if renderer == "presentation" or suffix in {".ppt", ".pptx"}:
            return "slide"
        return "word"

    @staticmethod
    def _material_preview_summary(material: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": str(material.get("name") or material.get("fileName") or material.get("materialId") or material.get("id") or ""),
            "folderPath": str(material.get("folderPath") or ""),
            "materialTier": str(material.get("materialTier") or material.get("libraryScope") or ""),
            "businessMaterialKind": str(material.get("businessMaterialKind") or ""),
            "businessMaterialKindLabel": str(material.get("businessMaterialKindLabel") or ""),
            "cleanStatus": str(material.get("cleanStatus") or ""),
            "hasCleanedWord": bool(material.get("hasCleanedWord")),
            "cleanedFileName": str(material.get("cleanedFileName") or ""),
            "turbineModelLabel": str(material.get("turbineModelLabel") or ""),
            "updatedAt": str(material.get("updatedAt") or ""),
        }

    def _completed_gap_state(self, project: dict[str, Any]) -> dict[str, Any]:
        business_gap_state = ensure_business_gap_state(project)
        if business_gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先生成商务标缺口计划。")
        return business_gap_state

    def _readable_material(self, project_id: str, material_id: str) -> dict[str, Any]:
        project = self.ensure_project(project_id)
        self._completed_gap_state(project)
        normalized_id = str(material_id or "").strip()
        if not normalized_id:
            raise KeyError("material_id")
        picker = build_business_gap_material_picker_index(project)
        for material in picker.get("materialIndex") or []:
            if not isinstance(material, dict):
                continue
            current_id = str(material.get("id") or material.get("materialId") or "").strip()
            if current_id == normalized_id:
                return {**material, "id": current_id}
        raise KeyError(normalized_id)

    def gaps(self, project_id: str, request: Request) -> dict[str, Any]:
        project = self._project_for_update(project_id)
        business_gap_state = ensure_business_gap_state(project)
        if business_gap_state["recognitionStatus"] == "completed":
            refreshed = False
            if refresh_template_candidates(project, business_gap_state):
                refreshed = True
            if refresh_material_kind_labels(project, business_gap_state):
                refreshed = True
            if refreshed:
                plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else {}
                self._finalize_plan_update(project, business_gap_state, plan, updated_at=now_iso())
                business_gap_state = ensure_business_gap_state(project)
        payload = self._build_gap_payload(project, business_gap_state)
        plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
        refresh_business_gap_artifact_urls(project_id, plan, **self._url_scope(request))
        payload["plan"] = plan
        payload["businessGapPlan"] = plan
        return payload

    @staticmethod
    def _build_gap_payload(project: dict[str, Any], business_gap_state: dict[str, Any]) -> dict[str, Any]:
        plan = copy.deepcopy(business_gap_state.get("plan") or {})
        summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else summarize_business_gap_plan(plan)
        return {
            "status": business_gap_state["recognitionStatus"],
            "recognizedAt": business_gap_state["recognizedAt"],
            "submittedForReview": bool(business_gap_state["submittedForReview"]),
            "reviewConfirmed": bool(business_gap_state["reviewConfirmed"]),
            "summary": copy.deepcopy(summary),
            "plan": plan,
            "businessGapPlan": copy.deepcopy(plan),
            "tocRefs": copy.deepcopy(plan.get("tocRefs") or []),
            "tasks": copy.deepcopy(plan.get("tasks") or []),
            "moduleGroups": copy.deepcopy(plan.get("moduleGroups") or []),
            "integrity": copy.deepcopy(business_gap_state.get("integrity") or {}),
            "source": {
                "fromStage": "商务标缺口处理",
                "projectId": project["id"],
                "projectName": project["name"],
                "bidType": require_bid_type(
                    project.get("bidType"),
                    error_message="商务缺口处理必须显式传入商务标项目。",
                ),
            },
        }

    def run_detection(self, project_id: str) -> dict[str, Any]:
        project = self._project_for_update(project_id)
        if str((project.get("outline_state") or {}).get("reviewStatus") or "") != "confirmed":
            raise ValueError("请先完成人工目录审核，再生成商务标缺口计划。")
        business_gap_state = ensure_business_gap_state(project)
        plan = build_business_gap_plan_for_project(project)
        record_business_gap_detection_result(
            project,
            business_gap_state,
            plan,
            recognized_at=now_iso(),
        )
        persist_business_gap_project(project)
        return self._gap_message(self._build_gap_payload(project, business_gap_state))

    def facts(self, project_id: str) -> dict[str, Any]:
        project = self._project_for_update(project_id)
        business_gap_state = ensure_business_gap_state(project)
        table = business_gap_state.get("projectFactTable") if isinstance(business_gap_state.get("projectFactTable"), dict) else {}
        if table.get("schemaVersion") == PROJECT_FACT_TABLE_SCHEMA_VERSION:
            return copy.deepcopy(table)
        return empty_project_fact_table(project_id)

    def selectable_materials(self, project_id: str, *, keyword: str = "") -> dict[str, Any]:
        project = self.ensure_project(project_id)
        self._completed_gap_state(project)
        picker = build_business_gap_material_picker_index(project)
        templates = [item for item in picker.get("templateIndex") or [] if isinstance(item, dict)]
        materials = [item for item in picker.get("materialIndex") or [] if isinstance(item, dict)]
        segments = [item for item in picker.get("evidenceSegments") or [] if isinstance(item, dict)]
        material_by_id = {
            str(item.get("id") or item.get("materialId") or ""): item
            for item in materials
            if str(item.get("id") or item.get("materialId") or "")
        }
        normalized_keyword = str(keyword or "").strip().lower()

        def matches(text: str) -> bool:
            return not normalized_keyword or normalized_keyword in str(text or "").lower()

        selectable_templates: list[dict[str, Any]] = []
        for template in templates:
            haystack = " ".join(
                [
                    str(template.get("templateName") or ""),
                    str(template.get("fileName") or ""),
                    str(template.get("sourceLabel") or ""),
                    str(template.get("sourceMode") or ""),
                    str(template.get("filePath") or ""),
                ]
            )
            if not matches(haystack):
                continue
            selectable_templates.append(
                {
                    "id": str(template.get("templateId") or template.get("filePath") or ""),
                    "kind": "template",
                    "templateId": str(template.get("templateId") or ""),
                    "templateName": str(template.get("templateName") or template.get("fileName") or ""),
                    "fileName": str(template.get("fileName") or ""),
                    "filePath": str(template.get("filePath") or ""),
                    "sourceMode": str(template.get("sourceMode") or ""),
                    "sourceLabel": str(template.get("sourceLabel") or ""),
                    "templateScope": str(template.get("templateScope") or ""),
                    "assemblyMode": "template_fill_docx",
                    "materialUsage": "fill_template",
                    "mimeType": str(template.get("mimeType") or ""),
                    "score": float(template.get("score") or 0),
                    "reason": str(template.get("reason") or ""),
                }
            )

        selectable_segments: list[dict[str, Any]] = []
        segments_by_material_id: dict[str, list[dict[str, Any]]] = {}
        for segment in segments:
            material_id = str(segment.get("material_id") or segment.get("materialId") or "").strip()
            material = material_by_id.get(material_id, {})
            if not material_id or not material:
                continue
            name = str(material.get("name") or material.get("fileName") or segment.get("title") or material_id)
            folder_path = str(material.get("folderPath") or segment.get("path") or "")
            haystack = " ".join(
                [
                    name,
                    folder_path,
                    str(segment.get("title") or ""),
                    str(segment.get("summary") or ""),
                    " ".join(str(item) for item in segment.get("keywords") or []),
                    str(segment.get("business_category") or ""),
                    str(segment.get("document_type") or ""),
                ]
            )
            if material_id and not matches(haystack):
                continue
            segment_item = {
                "id": str(segment.get("segment_id") or ""),
                "kind": "segment",
                "materialId": material_id,
                "materialName": name,
                "folderPath": folder_path,
                "materialTier": str(material.get("materialTier") or segment.get("material_tier") or ""),
                "businessMaterialKind": str(material.get("businessMaterialKind") or ""),
                "businessMaterialKindLabel": str(material.get("businessMaterialKindLabel") or ""),
                "cleanStatus": str(material.get("cleanStatus") or ""),
                "hasCleanedWord": bool(material.get("hasCleanedWord")),
                "cleanedFileName": str(material.get("cleanedFileName") or ""),
                "evidenceSegmentId": str(segment.get("segment_id") or ""),
                "evidenceSegmentTitle": str(segment.get("title") or ""),
                "evidenceSegmentType": str(segment.get("segment_type") or ""),
                "evidenceSourcePages": str(segment.get("source_pages") or ""),
                "evidenceSummary": str(segment.get("summary") or ""),
                "wikiCardId": str(segment.get("card_id") or ""),
                "wikiUsageMode": str(segment.get("usage_mode") or ""),
                "wikiEvidence": {
                    "validityStatus": str(segment.get("validity_status") or ""),
                    "expiryDate": str(segment.get("expiry_date") or ""),
                    "riskNotes": str(segment.get("risk_notes") or ""),
                    "ocrStatus": str(segment.get("ocr_status") or ""),
                    "ocrConfidence": str(segment.get("ocr_confidence") or ""),
                },
                "keywords": [str(item) for item in segment.get("keywords") or [] if str(item).strip()][:16],
                "updatedAt": str(material.get("updatedAt") or ""),
            }
            selectable_segments.append(segment_item)
            segments_by_material_id.setdefault(material_id, []).append(segment_item)

        material_ids_with_segments = {
            str(item.get("materialId") or "")
            for item in selectable_segments
            if str(item.get("materialId") or "")
        }
        selectable_materials: list[dict[str, Any]] = []
        for material in materials:
            material_id = str(material.get("id") or material.get("materialId") or "").strip()
            if not material_id:
                continue
            name = str(material.get("name") or material.get("fileName") or material_id)
            folder_path = str(material.get("folderPath") or "")
            haystack = " ".join(
                [
                    name,
                    folder_path,
                    str(material.get("cleanedFileName") or ""),
                    str(material.get("turbineModelLabel") or ""),
                    str(material.get("summary") or ""),
                    str(material.get("businessCategory") or ""),
                    str(material.get("documentType") or ""),
                    str(material.get("customerName") or ""),
                    str(material.get("projectType") or ""),
                    " ".join(str(item) for item in material.get("tags") or []),
                    " ".join(str(item) for item in material.get("keywords") or []),
                ]
            )
            if not matches(haystack):
                continue
            selectable_materials.append(
                {
                    "id": material_id,
                    "kind": "material",
                    "materialId": material_id,
                    "materialName": name,
                    "folderPath": folder_path,
                    "materialTier": str(material.get("materialTier") or ""),
                    "businessMaterialKind": str(material.get("businessMaterialKind") or ""),
                    "businessMaterialKindLabel": str(material.get("businessMaterialKindLabel") or ""),
                    "sourceType": str(material.get("sourceType") or ""),
                    "candidateType": str(material.get("candidateType") or ""),
                    "cleanStatus": str(material.get("cleanStatus") or ""),
                    "hasCleanedWord": bool(material.get("hasCleanedWord")),
                    "cleanedFileName": str(material.get("cleanedFileName") or ""),
                    "fileName": str(material.get("fileName") or ""),
                    "summary": str(material.get("summary") or ""),
                    "tags": [str(item) for item in material.get("tags") or [] if str(item).strip()][:16],
                    "keywords": [str(item) for item in material.get("keywords") or [] if str(item).strip()][:24],
                    "reviewStatus": str(material.get("reviewStatus") or ""),
                    "size": int(material.get("size") or 0),
                    "turbineModelLabel": str(material.get("turbineModelLabel") or ""),
                    "updatedAt": str(material.get("updatedAt") or ""),
                    "segmentCount": len(segments_by_material_id.get(material_id) or []),
                    "evidenceSegments": copy.deepcopy((segments_by_material_id.get(material_id) or [])[:8]),
                    "hasSegments": material_id in material_ids_with_segments,
                }
            )

        return {
            "schemaVersion": "bid-business-selectable-materials-v1",
            "projectId": project_id,
            "bidType": BUSINESS_BID_TYPE,
            "keyword": str(keyword or ""),
            "templates": selectable_templates,
            "items": selectable_materials,
            "segments": selectable_segments,
            "summary": {
                "templateCount": len(selectable_templates),
                "materialCount": len(selectable_materials),
                "segmentCount": len(selectable_segments),
                "wikiEvidenceSegmentCount": int((picker.get("businessWikiIndexSummary") or {}).get("evidenceSegmentCount") or 0),
            },
            "materialScope": copy.deepcopy(picker.get("materialScope") or {}),
            "selectedBusinessTurbineModel": copy.deepcopy(picker.get("selectedBusinessTurbineModel") or {}),
        }

    async def material_preview(
        self,
        project_id: str,
        material_id: str,
        request: Request,
        *,
        mode: str = "quick",
    ) -> dict[str, Any]:
        material = self._readable_material(project_id, material_id)
        if self._is_performance_material(material) and not str(material.get("wordObjectKey") or ""):
            quick_summary = self._material_preview_summary(material)
            return {
                "schemaVersion": "bid-business-material-preview-v1",
                "projectId": project_id,
                "materialId": str(material["id"]),
                "materialName": str(material.get("name") or material.get("fileName") or material["id"]),
                "fileName": str(material.get("fileName") or material.get("name") or material["id"]),
                "folderPath": str(material.get("folderPath") or ""),
                "materialTier": str(material.get("materialTier") or material.get("libraryScope") or ""),
                "businessMaterialKind": str(material.get("businessMaterialKind") or ""),
                "businessMaterialKindLabel": str(material.get("businessMaterialKindLabel") or ""),
                "mimeType": "",
                "renderer": "record",
                "browserFileUrl": "",
                "quickSummary": quick_summary,
                "cleanStatus": str(material.get("cleanStatus") or ""),
                "hasCleanedWord": False,
                "cleanedFileName": "",
                "officeAvailable": False,
                "previewMode": "metadata",
                "message": "该业绩暂未上传 Word 文件，可先核对业绩字段。",
            }
        payload, source_kind = await self._material_preview_download_payload(material)
        file_name = str(payload.get("fileName") or material.get("name") or material["id"])
        mime_type = str(payload.get("mimeType") or mimetypes.guess_type(file_name)[0] or "application/octet-stream")
        renderer = self._preview_renderer(file_name, mime_type)
        file_path = f"/api/business/projects/{project_id}/business-gaps/materials/{material['id']}/content/{safe_filename(file_name, 'material.bin')}"
        url_scope = self._url_scope(request)
        browser_base_url = url_scope["browser_base_url"]
        onlyoffice_base_url = url_scope["onlyoffice_base_url"]
        browser_file_url = f"{browser_base_url.rstrip('/')}{file_path}" if browser_base_url else file_path
        quick_summary = self._material_preview_summary(material)
        base = {
            "schemaVersion": "bid-business-material-preview-v1",
            "projectId": project_id,
            "materialId": str(material["id"]),
            "materialName": str(material.get("name") or file_name),
            "fileName": file_name,
            "folderPath": str(material.get("folderPath") or ""),
            "materialTier": str(material.get("materialTier") or ""),
            "businessMaterialKind": str(material.get("businessMaterialKind") or ""),
            "businessMaterialKindLabel": str(material.get("businessMaterialKindLabel") or ""),
            "mimeType": mime_type,
            "renderer": renderer,
            "browserFileUrl": browser_file_url,
            "quickSummary": quick_summary,
            "cleanStatus": str(material.get("cleanStatus") or ""),
            "hasCleanedWord": bool(material.get("hasCleanedWord")),
            "cleanedFileName": str(material.get("cleanedFileName") or ""),
            "officeAvailable": False,
            "message": "",
        }
        if renderer in {"image", "pdf"}:
            return {**base, "previewMode": "native", "message": "已生成浏览器原件预览。"}

        if renderer in {"word", "spreadsheet", "presentation"}:
            suffix = Path(file_name).suffix.lower().lstrip(".") or "docx"
            document_type = self._onlyoffice_document_type(file_name, renderer)
            document_server_url = f"{onlyoffice_base_url.rstrip('/')}{file_path}" if onlyoffice_base_url else browser_file_url
            return {
                **base,
                "previewMode": "onlyoffice",
                "renderer": renderer,
                "officeAvailable": True,
                "onlyoffice": {
                    "documentKey": f"business-gap-material-{material['id']}-{source_kind}-v{payload.get('version') or material.get('version') or 1}",
                    "title": file_name,
                    "fileUrl": document_server_url,
                    "browserFileUrl": browser_file_url,
                    "documentServerFileUrl": document_server_url,
                    "fileType": suffix,
                    "documentType": document_type,
                    "user": {
                        "id": "user-1",
                        "name": "当前用户",
                    },
                },
                "message": "已生成业绩 Word 预览。" if source_kind == "performance_library" else "已生成原素材 OnlyOffice 预览。",
            }

        return {
            **base,
            "previewMode": "download",
            "message": "该素材类型暂不支持内嵌预览，可打开或下载原件核对。",
        }

    async def material_preview_content(self, project_id: str, material_id: str) -> dict[str, Any]:
        material = self._readable_material(project_id, material_id)
        payload, _source_kind = await self._material_preview_download_payload(material)
        return payload

    @staticmethod
    def _is_performance_material(material: dict[str, Any] | None) -> bool:
        if not isinstance(material, dict):
            return False
        material_id = str(material.get("id") or material.get("materialId") or "")
        return str(material.get("sourceType") or "") == "performance_library" or material_id.startswith("PERF-")

    @staticmethod
    async def _material_preview_download_payload(material: dict[str, Any]) -> tuple[dict[str, Any], str]:
        material_id = str(material.get("id") or material.get("materialId") or "")
        if BusinessGapService._is_performance_material(material):
            return await performance_library_service.download_word(material_id), "performance_library"
        return await business_material_store.raw_download_content(material_id), "raw"

    @staticmethod
    async def _business_material_download_payload(material_id: str, material: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        if BusinessGapService._is_performance_material(material or {"id": material_id}):
            return await performance_library_service.download_word(material_id), "performance_library"
        try:
            payload = await business_material_store.raw_download_cleaned_content(material_id)
            return payload, "cleaned"
        except Exception:
            payload = await business_material_store.raw_download_content(material_id)
            return payload, "raw"

    async def build_facts(self, project_id: str) -> dict[str, Any]:
        project = self._project_for_update(project_id)
        business_gap_state = ensure_business_gap_state(project)
        if business_gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先生成商务标缺口计划，再维护项目事实表。")
        table = build_project_fact_table(project, business_gap_state)
        business_gap_state["projectFactTable"] = table
        project["updatedAt"] = now_iso()
        persist_business_gap_project(project)
        return copy.deepcopy(table)

    async def save_facts(self, project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = data or {}
        project = self._project_for_update(project_id)
        business_gap_state = ensure_business_gap_state(project)
        if business_gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先生成商务标缺口计划，再维护项目事实表。")
        current = business_gap_state.get("projectFactTable")
        if not isinstance(current, dict) or current.get("schemaVersion") != PROJECT_FACT_TABLE_SCHEMA_VERSION:
            current = build_project_fact_table(project, business_gap_state)
        raw_incoming_fields = payload.get("fields") if isinstance(payload.get("fields"), list) else current.get("fields") or []
        incoming_fields = normalize_business_fact_fields_for_save(raw_incoming_fields)
        confirm = bool(payload.get("confirm") or payload.get("confirmed"))
        operator = str(payload.get("operator") or "当前用户")
        saved_at = now_iso()
        fields = [
            normalize_project_fact_field(field, index=index, confirm=confirm, operator=operator, saved_at=saved_at)
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
            "summary": summarize_project_fact_fields(fields),
        }
        business_gap_state["projectFactTable"] = table
        project["updatedAt"] = saved_at
        persist_business_gap_project(project)
        return copy.deepcopy(table)

    def update_task(self, project_id: str, task_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = data or {}
        project = self._project_for_update(project_id)
        business_gap_state = ensure_business_gap_state(project)
        plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else {}
        task = find_task(plan, task_id)
        status = str(payload.get("status") or "").strip()
        if status == "ignored":
            task["status"] = "ignored"
            task["decision"] = str(payload.get("decision") or task.get("decision") or "ready")
            task["handlingMode"] = "ignored"
            task["ignoredReason"] = str(
                payload.get("reason") or payload.get("notes") or task.get("ignoredReason") or "人工忽略"
            )
            if "notes" in payload:
                task["notes"] = str(payload.get("notes") or "")
            task["updatedAt"] = now_iso()
            self._finalize_plan_update(
                project,
                business_gap_state,
                plan,
                updated_at=task["updatedAt"],
            )
            return {
                "task": copy.deepcopy(task),
                "plan": copy.deepcopy(plan),
                "integrity": copy.deepcopy(business_gap_state["integrity"]),
            }

        allowed = {
            "status",
            "decision",
            "selectedMaterialRefs",
            "notes",
            "confirmed",
            "riskFlags",
            "assemblyMode",
            "materialUsage",
            "fillPlan",
            "selectedEvidenceSegments",
            "handlingMode",
        }
        for key in allowed:
            if key in payload:
                task[key] = copy.deepcopy(payload[key])
        intent_changed = "assemblyMode" in payload or "materialUsage" in payload or "selectedEvidenceSegments" in payload
        explicit_status_change = "status" in payload or "decision" in payload
        if intent_changed:
            if "assemblyMode" in payload and "materialUsage" not in payload:
                task["materialUsage"] = material_usage_for_assembly_mode(
                    str(task.get("assemblyMode") or "")
                )
            elif not task.get("materialUsage"):
                task["materialUsage"] = material_usage_for_assembly_mode(
                    str(task.get("assemblyMode") or "")
                )
            task["fillPlan"] = task_fill_plan(task)
            if not explicit_status_change:
                recompute_task_after_artifact_change(task)
            if str(task.get("assemblyMode") or "") == "template_fill_docx":
                refresh_template_candidates(project, business_gap_state)
                plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else plan
                task = find_task(plan, task_id)
        task["updatedAt"] = now_iso()
        self._finalize_plan_update(project, business_gap_state, plan, updated_at=task["updatedAt"])
        return {
            "task": copy.deepcopy(task),
            "plan": copy.deepcopy(plan),
            "integrity": copy.deepcopy(business_gap_state["integrity"]),
        }

    def create_manual_task(
        self,
        project_id: str,
        toc_node_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = data or {}
        project = self._project_for_update(project_id)
        business_gap_state = ensure_business_gap_state(project)
        if business_gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先生成商务标缺口计划。")
        plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else {}
        toc_ref = find_toc_ref(plan, toc_node_id)
        tasks = plan.setdefault("tasks", [])
        if not isinstance(tasks, list):
            plan["tasks"] = tasks = []
        created_at = now_iso()
        existing_ids = {str(task.get("id") or "") for task in tasks if isinstance(task, dict)}
        base_index = len(tasks) + 1
        task_id = f"BTASK-MANUAL-{base_index:04d}"
        while task_id in existing_ids:
            base_index += 1
            task_id = f"BTASK-MANUAL-{base_index:04d}"
        title = str(payload.get("title") or "").strip() or f"{toc_ref.get('title') or '本章节'}补充材料"
        task = {
            "id": task_id,
            "taskKey": f"manual_{safe_filename(str(toc_ref.get('nodeId') or toc_node_id), 'toc')}_{base_index}",
            "title": title,
            "titleAlias": [],
            "moduleKey": str(payload.get("moduleKey") or "commitments_and_notes"),
            "taskType": str(payload.get("taskType") or "attachment"),
            "decision": "material_required",
            "status": "needs_input",
            "sourceType": "manual_user",
            "sourceRequirement": {
                "triggerText": str(
                    payload.get("requirement") or f"操作人针对目录章节「{toc_ref.get('title') or toc_node_id}」手动补充材料。"
                ),
                "triggerContext": "",
                "normalizedTopic": title,
                "fromSection": str(toc_ref.get("number") or ""),
                "extractionMethod": "manual_user",
            },
            "sourceEvidenceRefs": [],
            "tocTarget": {
                "nodeId": str(toc_ref.get("nodeId") or toc_node_id),
                "number": str(toc_ref.get("number") or ""),
                "title": str(toc_ref.get("title") or ""),
                "required": True,
            },
            "candidateMaterials": [],
            "selectedMaterialRefs": [],
            "resolvedArtifacts": [],
            "assemblyMode": default_task_assembly_mode(
                str(payload.get("moduleKey") or "commitments_and_notes"),
                str(payload.get("taskType") or "attachment"),
                "material_required",
                title,
            ),
            "materialUsage": "",
            "fillPlan": {},
            "selectedEvidenceSegments": [],
            "riskFlags": ["manual_upload_required"],
            "requirementLevel": "required",
            "assigneeMode": "manual_upload",
            "displayOrder": 9000 + base_index,
            "fingerprint": f"manual:{project_id}:{toc_node_id}:{base_index}",
            "updatedAt": created_at,
        }
        task["materialUsage"] = material_usage_for_assembly_mode(str(task.get("assemblyMode") or ""))
        task["fillPlan"] = task_fill_plan(task)
        tasks.append(task)
        task_ids = toc_ref.setdefault("taskIds", [])
        if task_id not in task_ids:
            task_ids.append(task_id)
        update_toc_ref_statuses(plan)
        self._finalize_plan_update(project, business_gap_state, plan, updated_at=created_at)
        return {
            "message": "已为当前目录章节创建人工补料任务。",
            "task": copy.deepcopy(task),
            "plan": copy.deepcopy(plan),
            "integrity": copy.deepcopy(business_gap_state["integrity"]),
        }

    def confirm_artifact(self, project_id: str, task_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = data or {}
        project = self._project_for_update(project_id)
        business_gap_state = ensure_business_gap_state(project)
        plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else {}
        task = find_task(plan, task_id)
        artifact_id = str(payload.get("artifactId") or "").strip()
        confirmed = bool(payload.get("confirmed", True))
        artifacts = task.get("resolvedArtifacts") if isinstance(task.get("resolvedArtifacts"), list) else []
        artifact = None
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            if not artifact_id or artifact_id == str(item.get("artifactId") or ""):
                artifact = item
                break
        if artifact is None:
            raise KeyError(artifact_id or task_id)
        artifact["confirmed"] = confirmed
        artifact["reviewStatus"] = "approved" if confirmed else "pending_review"
        artifact["confirmedAt"] = now_iso() if confirmed else ""
        if confirmed:
            task["decision"] = "ready"
            task["status"] = "ready"
            task["riskFlags"] = [
                flag
                for flag in (task.get("riskFlags") if isinstance(task.get("riskFlags"), list) else [])
                if flag not in {"missing_material", "parser_generated_unconfirmed"}
            ]
        else:
            task["decision"] = "review_required"
            task["status"] = "review_required"
        task["updatedAt"] = now_iso()
        self._finalize_plan_update(project, business_gap_state, plan, updated_at=task["updatedAt"])
        return {"task": copy.deepcopy(task), "artifact": copy.deepcopy(artifact), "plan": copy.deepcopy(plan)}

    def upload_artifact(
        self,
        project_id: str,
        task_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = data or {}
        project = self._project_for_update(project_id)
        business_gap_state = ensure_business_gap_state(project)
        if business_gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先生成商务标缺口计划。")
        plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else {}
        task = find_task(plan, task_id)
        files = [entry for entry in payload.get("files") or [] if isinstance(entry, dict)]
        if not files:
            raise ValueError("至少需要上传一个文件。")

        upload_records: list[dict[str, Any]] = []
        for index, file in enumerate(files, start=1):
            source_name = str(file.get("name") or file.get("fileName") or f"{task_id}-{index}.bin")
            content = str(
                file.get("data")
                or file.get("dataUrl")
                or file.get("content")
                or file.get("base64")
                or file.get("base64Content")
                or ""
            )
            raw_bytes, mime_type = decode_upload_content(
                content,
                fallback_mime=str(file.get("mimeType") or ""),
            )
            upload_records.append(
                {
                    "name": source_name,
                    "mimeType": mime_type or str(file.get("mimeType") or ""),
                    "rawBytes": raw_bytes,
                }
            )
        return self._register_upload_records(
            project,
            business_gap_state,
            plan,
            task,
            upload_records,
            operator=str(payload.get("operator") or "当前用户"),
            **self._url_scope(request),
        )

    def upload_artifact_files(
        self,
        project_id: str,
        task_id: str,
        request: Request,
        records: list[dict[str, Any]],
        *,
        operator: str = "当前用户",
    ) -> dict[str, Any]:
        project = self._project_for_update(project_id)
        business_gap_state = ensure_business_gap_state(project)
        if business_gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先生成商务标缺口计划。")
        plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else {}
        task = find_task(plan, task_id)
        return self._register_upload_records(
            project,
            business_gap_state,
            plan,
            task,
            records,
            operator=operator,
            **self._url_scope(request),
        )

    def _register_upload_records(
        self,
        project: dict[str, Any],
        business_gap_state: dict[str, Any],
        plan: dict[str, Any],
        task: dict[str, Any],
        files: list[dict[str, Any]],
        *,
        operator: str,
        browser_base_url: str = "",
        onlyoffice_base_url: str = "",
    ) -> dict[str, Any]:
        project_id = str(project.get("id") or "")
        task_id = str(task.get("id") or task.get("taskKey") or "task")
        records = [entry for entry in files if isinstance(entry, dict)]
        if not records:
            raise ValueError("至少需要上传一个文件。")
        work_dir = business_workspace_dir(project_id) / "gaps" / "uploads" / safe_filename(task_id, "task")
        work_dir.mkdir(parents=True, exist_ok=True)
        created_at = now_iso()
        artifacts: list[dict[str, Any]] = []
        existing_count = len(task.get("resolvedArtifacts") if isinstance(task.get("resolvedArtifacts"), list) else [])
        for index, file in enumerate(records, start=1):
            source_name = str(file.get("name") or file.get("fileName") or f"{task_id}-{index}.bin")
            file_name = safe_filename(source_name, f"{task_id}-{index}.bin")
            raw_bytes = file.get("rawBytes") or file.get("bytes") or b""
            if isinstance(raw_bytes, str):
                raw_bytes, mime_type = decode_upload_content(
                    raw_bytes,
                    fallback_mime=str(file.get("mimeType") or ""),
                )
            else:
                raw_bytes = bytes(raw_bytes or b"")
                mime_type = str(file.get("mimeType") or "")
            if not raw_bytes:
                raise ValueError(f"上传文件内容为空：{file_name}")
            target_path = unique_path(work_dir, file_name)
            target_path.write_bytes(raw_bytes)
            artifact_id = f"BART-{safe_filename(task_id, 'TASK')}-UPLOAD-{existing_count + index}"
            artifact = {
                "artifactId": artifact_id,
                "artifactType": "manual_upload",
                "fileName": target_path.name,
                "filePath": str(target_path),
                "sourceMode": "uploaded_in_business_s3",
                "assemblyMode": assembly_mode_for_artifact(
                    task,
                    {"fileName": target_path.name, "mimeType": mime_type},
                ),
                "materialUsage": "",
                "materialSourceType": "manual_upload",
                "materialSyncStatus": "not_synced",
                "materialSyncPolicy": "manual_project_only",
                "materialTargetPath": default_material_target_path(project_id, task),
                "wikiSyncStatus": "not_synced",
                "version": 1,
                "previewable": True,
                "confirmed": True,
                "reviewStatus": "approved",
                "confirmedAt": created_at,
                "uploadedAt": created_at,
                "operator": operator or "当前用户",
                "mimeType": mime_type or mimetypes.guess_type(target_path.name)[0] or "application/octet-stream",
            }
            artifact["materialUsage"] = material_usage_for_assembly_mode(
                str(artifact.get("assemblyMode") or "")
            )
            artifacts.append(artifact)

        task.setdefault("resolvedArtifacts", []).extend(artifacts)
        apply_task_artifact_intent(task, artifacts)
        task["decision"] = "ready"
        task["status"] = "ready"
        task["handlingMode"] = "manual_upload"
        task["updatedAt"] = created_at
        task["resolvedAt"] = created_at
        task["resolvedSource"] = artifacts[0]["fileName"]
        task["riskFlags"] = [
            flag
            for flag in (task.get("riskFlags") if isinstance(task.get("riskFlags"), list) else [])
            if flag not in {"missing_material", "manual_upload_required", "ai_draft_required"}
        ]
        self._finalize_plan_update(project, business_gap_state, plan, updated_at=created_at)
        self._refresh_plan_urls(
            project_id,
            plan,
            {
                "browser_base_url": browser_base_url,
                "onlyoffice_base_url": onlyoffice_base_url,
            },
        )
        return {
            "task": copy.deepcopy(task),
            "artifact": copy.deepcopy(artifacts[0]),
            "artifacts": copy.deepcopy(artifacts),
            "plan": copy.deepcopy(plan),
            "integrity": copy.deepcopy(business_gap_state["integrity"]),
        }

    def remove_artifact(self, project_id: str, task_id: str, artifact_id: str, request: Request) -> dict[str, Any]:
        project = self._project_for_update(project_id)
        business_gap_state = ensure_business_gap_state(project)
        if business_gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先生成商务标缺口计划。")
        plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else {}
        task = find_task(plan, task_id)
        artifacts = task.get("resolvedArtifacts") if isinstance(task.get("resolvedArtifacts"), list) else []
        target = str(artifact_id or "").strip()
        kept: list[dict[str, Any]] = []
        removed: dict[str, Any] | None = None
        for artifact in artifacts:
            if isinstance(artifact, dict) and str(artifact.get("artifactId") or "") == target:
                removed = artifact
                continue
            if isinstance(artifact, dict):
                kept.append(artifact)
        if removed is None:
            raise KeyError(artifact_id)
        if str(removed.get("sourceMode") or "") not in {"uploaded_in_business_s3", "selected_from_business_material_library"}:
            raise ValueError("解析生成产物不能在 S3 页面直接取消，请在解析产物审核处处理。")
        if str(removed.get("materialSyncStatus") or "") == "synced_to_project_material":
            raise ValueError("该补料已同步到项目素材库，不能直接取消；如需删除，请在素材库中处理。")

        file_path = Path(str(removed.get("filePath") or ""))
        if file_path.exists() and file_path.is_file():
            try:
                file_path.unlink()
            except OSError:
                removed["deleteWarning"] = "文件删除失败，仅从当前任务中移除记录。"

        task["resolvedArtifacts"] = kept
        removed_material_id = str(removed.get("materialId") or "")
        if removed_material_id and isinstance(task.get("selectedMaterialRefs"), list):
            task["selectedMaterialRefs"] = [
                ref
                for ref in task["selectedMaterialRefs"]
                if not isinstance(ref, dict) or str(ref.get("materialId") or ref.get("id") or "") != removed_material_id
            ]
        recompute_task_after_artifact_change(task)
        updated_at = now_iso()
        task["updatedAt"] = updated_at
        self._finalize_plan_update(project, business_gap_state, plan, updated_at=updated_at)
        self._refresh_plan_urls(project_id, plan, self._url_scope(request))
        return {
            "message": "已取消该补料。",
            "task": copy.deepcopy(task),
            "artifact": copy.deepcopy(removed),
            "plan": copy.deepcopy(plan),
            "integrity": copy.deepcopy(business_gap_state["integrity"]),
        }

    async def select_material(
        self,
        project_id: str,
        task_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = data or {}
        project = self._project_for_update(project_id)
        business_gap_state = ensure_business_gap_state(project)
        if business_gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先生成商务标缺口计划。")
        plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else {}
        task = find_task(plan, task_id)
        selected = selected_material_entries(payload)
        if not selected:
            raise ValueError("至少需要选择一份素材。")

        work_dir = business_workspace_dir(project_id) / "gaps" / "selected-materials" / safe_filename(task_id, "task")
        work_dir.mkdir(parents=True, exist_ok=True)
        created_at = now_iso()
        existing_count = len(task.get("resolvedArtifacts") if isinstance(task.get("resolvedArtifacts"), list) else [])
        material_refs: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        for index, material in enumerate(selected, start=1):
            material_id = str(material.get("id") or material.get("materialId") or "").strip()
            if not material_id:
                continue
            material_context = dict(material)
            if self._is_performance_material({**material_context, "id": material_id}):
                try:
                    readable_material = self._readable_material(project_id, material_id)
                    material_context = {**readable_material, **material_context}
                except Exception:
                    material_context = {**material_context, "id": material_id, "sourceType": "performance_library"}
            raw_payload, source_kind = await self._business_material_download_payload(material_id, material_context)
            raw_name = safe_filename(
                str(raw_payload.get("fileName") or material_context.get("materialName") or material_context.get("name") or f"{material_id}.bin"),
                f"{material_id}.bin",
            )
            target_path = unique_path(work_dir, f"{index:02d}-{raw_name}")
            minio_client.download_file(str(raw_payload["bucket"]), str(raw_payload["key"]), target_path)
            mime_type = str(raw_payload.get("mimeType") or mimetypes.guess_type(target_path.name)[0] or "application/octet-stream")
            cleaned_snapshot: dict[str, Any] = {}
            if source_kind != "performance_library":
                try:
                    cleaned_payload = await business_material_store.raw_download_cleaned_content(material_id)
                    cleaned_name = safe_filename(
                        str(cleaned_payload.get("fileName") or material_context.get("cleanedFileName") or f"{material_id}-cleaned.docx"),
                        f"{material_id}-cleaned.docx",
                    )
                    cleaned_target_path = unique_path(work_dir, f"{index:02d}-清洗稿-{cleaned_name}")
                    minio_client.download_file(str(cleaned_payload["bucket"]), str(cleaned_payload["key"]), cleaned_target_path)
                    if cleaned_target_path.exists():
                        cleaned_snapshot = {
                            "cleanedFileName": cleaned_target_path.name,
                            "cleanedFilePath": str(cleaned_target_path),
                            "cleanedMimeType": str(
                                cleaned_payload.get("mimeType")
                                or mimetypes.guess_type(cleaned_target_path.name)[0]
                                or "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                            ),
                        }
                        source_kind = "raw_with_cleaned"
                except Exception:
                    cleaned_snapshot = {}
            ref = {
                "materialId": material_id,
                "materialName": str(
                    material_context.get("materialName")
                    or material_context.get("name")
                    or raw_payload.get("fileName")
                    or material_id
                ),
                "folderPath": str(material_context.get("folderPath") or material_context.get("path") or ""),
                "materialTier": str(material_context.get("materialTier") or material_context.get("libraryScope") or ""),
                "businessMaterialKind": str(material_context.get("businessMaterialKind") or ""),
                "businessMaterialKindLabel": str(material_context.get("businessMaterialKindLabel") or ""),
                "sourceKind": source_kind,
                "sourceType": str(material_context.get("sourceType") or ""),
                "selectedAt": created_at,
            }
            artifact_id = f"BART-{safe_filename(task_id, 'TASK')}-MAT-{existing_count + index}"
            artifact = {
                "artifactId": artifact_id,
                "artifactType": "selected_material",
                "fileName": target_path.name,
                "filePath": str(target_path),
                "sourceMode": "selected_from_business_material_library",
                "assemblyMode": assembly_mode_for_artifact(
                    task,
                    {**material_context, "fileName": target_path.name, "mimeType": mime_type},
                ),
                "materialUsage": str(material_context.get("wikiUsageMode") or ""),
                "materialSourceType": "performance_library" if source_kind == "performance_library" else "material_library",
                "materialId": material_id,
                "materialName": ref["materialName"],
                "folderPath": ref["folderPath"],
                "materialTier": ref["materialTier"],
                "businessMaterialKind": ref["businessMaterialKind"],
                "businessMaterialKindLabel": ref["businessMaterialKindLabel"],
                "sourceKind": source_kind,
                "sourceType": ref["sourceType"],
                "version": 1,
                "previewable": True,
                "confirmed": True,
                "reviewStatus": "approved",
                "confirmedAt": created_at,
                "selectedAt": created_at,
                "operator": str(payload.get("operator") or "当前用户"),
                "mimeType": mime_type,
                "wikiCardId": str(material_context.get("wikiCardId") or ""),
                "wikiUsageMode": str(material_context.get("wikiUsageMode") or ""),
                "evidenceSegmentId": str(material_context.get("evidenceSegmentId") or ""),
                "evidenceSegmentTitle": str(material_context.get("evidenceSegmentTitle") or ""),
                "evidenceSegmentType": str(material_context.get("evidenceSegmentType") or ""),
                "evidenceSourcePages": str(material_context.get("evidenceSourcePages") or ""),
                "evidenceSummary": str(material_context.get("evidenceSummary") or material_context.get("summary") or ""),
                "selectedEvidenceSegments": copy.deepcopy(
                    material_context.get("evidenceSegments") if isinstance(material_context.get("evidenceSegments"), list) else []
                ),
                "wikiEvidence": copy.deepcopy(material_context.get("wikiEvidence") or {}),
                "rawFileName": target_path.name,
                "rawFilePath": str(target_path),
                "rawMimeType": mime_type,
                **cleaned_snapshot,
            }
            if not artifact["materialUsage"]:
                artifact["materialUsage"] = material_usage_for_assembly_mode(
                    str(artifact.get("assemblyMode") or "")
                )
            material_refs.append(ref)
            artifacts.append(artifact)

        if not artifacts:
            raise ValueError("至少需要选择一份有效素材。")
        existing_refs = task.get("selectedMaterialRefs") if isinstance(task.get("selectedMaterialRefs"), list) else []
        task["selectedMaterialRefs"] = merge_material_refs(existing_refs, material_refs)
        task.setdefault("resolvedArtifacts", []).extend(artifacts)
        apply_task_artifact_intent(task, artifacts)
        record_business_material_feedback(
            business_gap_state,
            task,
            artifacts,
            operator=str(payload.get("operator") or "当前用户"),
            selected_at=created_at,
        )
        task["decision"] = "ready"
        task["status"] = "ready"
        explicit_mode = str(payload.get("handlingMode") or "")
        if not explicit_mode:
            explicit_mode = next((str(material.get("handlingMode") or "") for material in selected if str(material.get("handlingMode") or "")), "")
        explicit_mode = explicit_mode.strip()
        if explicit_mode == "manual_select":
            explicit_mode = "manual_upload"
        if explicit_mode not in {"fixed_material", "manual_upload", "ignored", "ai_table_fill"}:
            explicit_mode = ""
        if explicit_mode:
            task["handlingMode"] = explicit_mode
        elif any(str(artifact.get("businessMaterialKind") or "") == "fixed" for artifact in artifacts):
            task["handlingMode"] = "fixed_material"
        else:
            task["handlingMode"] = "manual_upload"
        task["updatedAt"] = created_at
        task["resolvedAt"] = created_at
        task["resolvedSource"] = artifacts[0]["fileName"]
        task["riskFlags"] = [
            flag
            for flag in (task.get("riskFlags") if isinstance(task.get("riskFlags"), list) else [])
            if flag not in {"missing_material"}
        ]
        self._finalize_plan_update(project, business_gap_state, plan, updated_at=created_at)
        self._refresh_plan_urls(project_id, plan, self._url_scope(request))
        return {
            "task": copy.deepcopy(task),
            "artifact": copy.deepcopy(artifacts[0]),
            "artifacts": copy.deepcopy(artifacts),
            "selectedMaterialRefs": copy.deepcopy(task["selectedMaterialRefs"]),
            "plan": copy.deepcopy(plan),
            "integrity": copy.deepcopy(business_gap_state["integrity"]),
        }

    def select_template(
        self,
        project_id: str,
        task_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = data or {}
        project = self._project_for_update(project_id)
        business_gap_state = ensure_business_gap_state(project)
        if business_gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先生成商务标缺口计划。")
        plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else {}
        task = find_task(plan, task_id)
        selected = selected_template_entry(task, payload)
        source_path = Path(str(selected.get("filePath") or selected.get("path") or "")).expanduser()
        if not source_path.exists() or not source_path.is_file():
            raise ValueError("候选模板文件不存在，请重新生成商务标缺口计划或重新上传模板。")
        if source_path.suffix.lower() != ".docx":
            raise ValueError("模板填充 Word 目前仅支持 DOCX 模板。")

        work_dir = business_workspace_dir(project_id) / "gaps" / "selected-templates" / safe_filename(task_id, "task")
        work_dir.mkdir(parents=True, exist_ok=True)
        created_at = now_iso()
        existing_count = len(task.get("resolvedArtifacts") if isinstance(task.get("resolvedArtifacts"), list) else [])
        target_path = unique_path(work_dir, source_path.name)
        shutil.copy2(source_path, target_path)
        artifact = {
            "artifactId": f"BART-{safe_filename(task_id, 'TASK')}-TPL-{existing_count + 1}",
            "artifactType": "selected_bid_template",
            "fileName": target_path.name,
            "filePath": str(target_path),
            "sourceMode": str(selected.get("sourceMode") or "selected_from_bid_template"),
            "templateId": str(selected.get("templateId") or ""),
            "templateName": str(selected.get("templateName") or selected.get("fileName") or target_path.name),
            "templateScope": str(selected.get("templateScope") or ""),
            "sourceLabel": str(selected.get("sourceLabel") or ""),
            "assemblyMode": "template_fill_docx",
            "materialUsage": "fill_template",
            "version": 1,
            "previewable": True,
            "confirmed": True,
            "reviewStatus": "approved",
            "confirmedAt": created_at,
            "selectedAt": created_at,
            "operator": str(payload.get("operator") or "当前用户"),
            "mimeType": str(
                mimetypes.guess_type(target_path.name)[0]
                or "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
        }
        task.setdefault("resolvedArtifacts", []).append(artifact)
        apply_task_artifact_intent(task, [artifact])
        recompute_task_after_artifact_change(task)
        task["handlingMode"] = "manual_upload"
        task["updatedAt"] = created_at
        task["resolvedAt"] = created_at
        task["resolvedSource"] = artifact["fileName"]
        self._finalize_plan_update(project, business_gap_state, plan, updated_at=created_at)
        self._refresh_plan_urls(project_id, plan, self._url_scope(request))
        return {
            "message": "已选择模板并快照到商务 S3 工作区。",
            "task": copy.deepcopy(task),
            "artifact": copy.deepcopy(artifact),
            "plan": copy.deepcopy(plan),
            "integrity": copy.deepcopy(business_gap_state["integrity"]),
        }

    async def ai_draft(
        self,
        project_id: str,
        task_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = data or {}
        project = self._project_for_update(project_id)
        business_s1_consumption_context(project)
        business_gap_state = ensure_business_gap_state(project)
        if business_gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先生成商务标缺口计划。")
        plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else {}
        task = find_task(plan, task_id)
        if not task_can_ai_draft(task):
            raise ValueError("该任务不适合 AI 起草，请选择候选素材或人工上传补料。")

        fact_table = business_gap_state.get("projectFactTable")
        if not isinstance(fact_table, dict) or fact_table.get("schemaVersion") != PROJECT_FACT_TABLE_SCHEMA_VERSION:
            fact_table = build_project_fact_table(project, business_gap_state)
            business_gap_state["projectFactTable"] = fact_table
        facts = fact_table_value_map(fact_table)
        created_at = now_iso()
        work_dir = business_workspace_dir(project_id) / "gaps" / "ai-drafts" / safe_filename(task_id, "task")
        work_dir.mkdir(parents=True, exist_ok=True)
        existing_count = len(task.get("resolvedArtifacts") if isinstance(task.get("resolvedArtifacts"), list) else [])
        title = str(task.get("title") or "商务响应文件")
        output_path = unique_path(work_dir, f"{safe_filename(title, '商务响应文件')}-AI起草.docx")
        write_business_ai_draft_docx(output_path, project, task, facts, payload)

        artifact_id = f"BART-{safe_filename(task_id, 'TASK')}-AI-{existing_count + 1}"
        artifact = {
            "artifactId": artifact_id,
            "artifactType": "ai_draft",
            "fileName": output_path.name,
            "filePath": str(output_path),
            "sourceMode": "generated_by_business_s3_ai_draft",
            "version": 1,
            "previewable": True,
            "confirmed": True,
            "reviewStatus": "approved",
            "confirmedAt": created_at,
            "createdAt": created_at,
            "operator": str(payload.get("operator") or "当前用户"),
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "assemblyMode": "ai_draft",
            "materialUsage": "generate_draft",
            "draftMode": "controlled_business_ai_draft",
            "draftPolicy": "only_for_s3_ai_draft_task",
            "factTableStatus": str(fact_table.get("status") or "draft"),
        }
        task.setdefault("resolvedArtifacts", []).append(artifact)
        apply_task_artifact_intent(task, [artifact])
        task["decision"] = "ready"
        task["status"] = "ready"
        task["assigneeMode"] = "ai_draft"
        task["updatedAt"] = created_at
        task["resolvedAt"] = created_at
        task["resolvedSource"] = artifact["fileName"]
        task["riskFlags"] = [
            flag
            for flag in (task.get("riskFlags") if isinstance(task.get("riskFlags"), list) else [])
            if flag not in {"missing_material", "manual_upload_required", "ai_draft_required"}
        ]
        if str(fact_table.get("status") or "") != "confirmed":
            flags = task.setdefault("riskFlags", [])
            if isinstance(flags, list) and "fact_table_unconfirmed" not in flags:
                flags.append("fact_table_unconfirmed")
        self._finalize_plan_update(project, business_gap_state, plan, updated_at=created_at)
        self._refresh_plan_urls(project_id, plan, self._url_scope(request))
        return {
            "message": "已生成商务响应文件 AI 起草稿。",
            "task": copy.deepcopy(task),
            "artifact": copy.deepcopy(artifact),
            "plan": copy.deepcopy(plan),
            "integrity": copy.deepcopy(business_gap_state["integrity"]),
            "projectFactTable": copy.deepcopy(fact_table),
        }

    async def table_fill(
        self,
        project_id: str,
        task_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._run_table_fill,
            project_id,
            task_id,
            data or {},
            self._url_scope(request),
        )

    def _run_table_fill(
        self,
        project_id: str,
        task_id: str,
        data: dict[str, Any],
        url_scope: dict[str, str],
    ) -> dict[str, Any]:
        project = self._project_for_update(project_id)
        s1_context = business_s1_consumption_context(project)
        business_gap_state = ensure_business_gap_state(project)
        if business_gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先生成商务标缺口计划。")
        plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else {}
        task = find_task(plan, task_id)

        target = table_fill_target(task, data)
        fact_table = business_gap_state.get("projectFactTable")
        if not isinstance(fact_table, dict) or fact_table.get("schemaVersion") != PROJECT_FACT_TABLE_SCHEMA_VERSION:
            fact_table = build_project_fact_table(project, business_gap_state)
            business_gap_state["projectFactTable"] = fact_table
        source_materials = business_table_fill_source_materials(project, data)

        created_at = now_iso()
        work_dir = business_workspace_dir(project_id) / "gaps" / "table-fill" / safe_filename(task_id, "task")
        work_dir.mkdir(parents=True, exist_ok=True)
        target = prepare_business_table_fill_target(target, work_dir)
        prepared_sources = prepare_business_table_fill_sources(source_materials, work_dir)
        output_name = (
            f"{safe_filename(str(target.get('name') or target.get('fileName') or task.get('title') or '商务填写'), '商务填写')}"
            "-AI填写.docx"
        )
        output_path = unique_path(work_dir, output_name)
        manifest_path = work_dir / "business_table_fill_input.json"
        manifest = {
            "schemaVersion": "bid-business-table-fill-v1",
            "projectId": project_id,
            "projectName": str(project.get("name") or ""),
            "task": {
                "id": str(task.get("id") or ""),
                "title": str(task.get("title") or ""),
                "requirement": str(task.get("requirement") or task.get("gapReason") or ""),
                "moduleKey": str(task.get("moduleKey") or ""),
            },
            "target": target,
            "sourceMaterials": prepared_sources,
            "projectFactTable": fact_table,
            "facts": fact_table_value_map(fact_table),
            "s1Consumption": {
                "source": str(s1_context.get("source") or "legacy_parse_result"),
                "structuredResultPath": str(s1_context.get("structuredResultPath") or ""),
                "handoff": copy.deepcopy(s1_context.get("handoff") if isinstance(s1_context.get("handoff"), dict) else {}),
            },
            "operator": str(data.get("operator") or "当前用户"),
            "outputFile": str(output_path),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        result = run_business_table_fill_skill(manifest_path)
        resolved_output = Path(str(result.get("outputFile") or output_path))
        if not resolved_output.exists():
            raise RuntimeError(f"AI填写未生成输出文件：{resolved_output}")

        existing_count = len(task.get("resolvedArtifacts") if isinstance(task.get("resolvedArtifacts"), list) else [])
        artifact_id = f"BART-{safe_filename(task_id, 'TASK')}-TBL-{existing_count + 1}"
        artifact = {
            "artifactId": artifact_id,
            "artifactType": "business_table_fill",
            "fileName": resolved_output.name,
            "filePath": str(resolved_output),
            "sourceMode": "generated_by_business_table_fill",
            "assemblyMode": "table_fill_from_material",
            "materialUsage": "fill_table",
            "version": 1,
            "previewable": True,
            "confirmed": True,
            "reviewStatus": "approved",
            "confirmedAt": created_at,
            "createdAt": created_at,
            "operator": str(data.get("operator") or "当前用户"),
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "target": copy.deepcopy(target),
            "sourceMaterials": copy.deepcopy(source_materials),
            "manifestPath": str(manifest_path),
            "fillReport": copy.deepcopy(result.get("fillReport") if isinstance(result.get("fillReport"), dict) else {}),
            "unfilledFields": copy.deepcopy(result.get("unfilledFields") if isinstance(result.get("unfilledFields"), list) else []),
            "evidenceRefs": copy.deepcopy(result.get("evidenceRefs") if isinstance(result.get("evidenceRefs"), list) else []),
            "opencodeOutput": copy.deepcopy(result.get("opencodeOutput") if isinstance(result.get("opencodeOutput"), dict) else {}),
        }
        task.setdefault("resolvedArtifacts", []).append(artifact)
        apply_task_artifact_intent(task, [artifact])
        task["decision"] = "ready"
        task["status"] = "ready"
        task["handlingMode"] = "ai_table_fill"
        task["updatedAt"] = created_at
        task["resolvedAt"] = created_at
        task["resolvedSource"] = artifact["fileName"]
        task["riskFlags"] = [
            flag
            for flag in (task.get("riskFlags") if isinstance(task.get("riskFlags"), list) else [])
            if flag not in {"missing_material", "manual_upload_required", "ai_draft_required", "fact_table_unconfirmed"}
        ]
        if str(fact_table.get("status") or "") != "confirmed":
            flags = task.setdefault("riskFlags", [])
            if isinstance(flags, list) and "fact_table_unconfirmed" not in flags:
                flags.append("fact_table_unconfirmed")
        self._finalize_plan_update(project, business_gap_state, plan, updated_at=created_at)
        self._refresh_plan_urls(project_id, plan, url_scope)
        return {
            "message": "AI填写产物已生成。",
            "task": copy.deepcopy(task),
            "artifact": copy.deepcopy(artifact),
            "plan": copy.deepcopy(plan),
            "integrity": copy.deepcopy(business_gap_state["integrity"]),
            "projectFactTable": copy.deepcopy(fact_table),
        }

    async def sync_artifact_to_material(
        self,
        project_id: str,
        task_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = data or {}
        project = self._project_for_update(project_id)
        business_gap_state = ensure_business_gap_state(project)
        if business_gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先生成商务标缺口计划。")
        plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else {}
        task = find_task(plan, task_id)
        artifact_id = str(payload.get("artifactId") or "").strip()
        if not artifact_id:
            raise ValueError("artifactId 不能为空。")
        artifact = find_artifact_in_task(task, artifact_id)
        if str(artifact.get("sourceMode") or "") != "uploaded_in_business_s3":
            raise ValueError("仅支持将人工上传的 S3 补料同步到商务标项目素材库。")
        source_path = Path(str(artifact.get("filePath") or ""))
        if not source_path.exists() or not source_path.is_file():
            raise ValueError("补料文件不存在，无法同步。")

        target_path = str(payload.get("targetPath") or "").strip().strip("/")
        if not target_path:
            target_path = default_material_target_path(project_id, task)
        project_material_root = project_material_root_path(BUSINESS_BID_TYPE, project_id)
        if not target_path.startswith(f"{project_material_root}/"):
            raise ValueError("S3 补料默认只允许同步到当前商务标项目素材库。")

        raw_bytes = source_path.read_bytes()
        upload_result = await business_material_store.raw_upload(
            target_path=target_path,
            project_id=project_id,
            project_code=str(project.get("projectCode") or project_id),
            project_name=str(project.get("name") or project_id),
            material_tier="project",
            customer_id=str(project.get("customerId") or ""),
            customer_name=str(project.get("customerCanonicalName") or project.get("customerName") or project.get("owner") or ""),
            on_conflict="version",
            files=[
                {
                    "name": str(artifact.get("fileName") or source_path.name),
                    "mimeType": str(artifact.get("mimeType") or mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"),
                    "data": base64.b64encode(raw_bytes).decode("ascii"),
                }
            ],
        )
        synced_items = [item for item in upload_result.get("items") or [] if isinstance(item, dict)]
        if not synced_items:
            raise ValueError("补料同步失败：素材库未返回上传文件。")
        synced = synced_items[0]
        synced_at = now_iso()
        artifact["materialSyncStatus"] = "synced_to_project_material"
        artifact["materialSyncedAt"] = synced_at
        artifact["materialTargetPath"] = target_path
        artifact["materialId"] = str(synced.get("id") or "")
        artifact["materialName"] = str(synced.get("name") or artifact.get("fileName") or "")
        artifact["materialTier"] = str(synced.get("materialTier") or "project")
        artifact["folderPath"] = str(synced.get("folderPath") or target_path)
        artifact["cleanStatus"] = str(synced.get("cleanStatus") or "")
        artifact["cleanMessage"] = str(synced.get("cleanMessage") or "")
        artifact["wikiSyncStatus"] = "wiki_rebuild_required"
        task["updatedAt"] = synced_at
        add_note = f"补料已同步到项目素材库：{target_path}"
        task["notes"] = "\n".join(part for part in [str(task.get("notes") or "").strip(), add_note] if part)
        business_gap_state["wikiRebuildRequired"] = True
        business_gap_state["lastMaterialSyncAt"] = synced_at
        business_gap_state["lastMaterialSyncTargetPath"] = target_path
        self._finalize_plan_update(project, business_gap_state, plan, updated_at=synced_at)
        self._refresh_plan_urls(project_id, plan, self._url_scope(request))
        return {
            "message": "补料已同步到商务标项目素材库，商务 Wiki 需要重新生成/更新。",
            "task": copy.deepcopy(task),
            "artifact": copy.deepcopy(artifact),
            "material": copy.deepcopy(synced),
            "materialUpload": copy.deepcopy(upload_result),
            "wikiRebuildRequired": True,
            "plan": copy.deepcopy(plan),
            "integrity": copy.deepcopy(business_gap_state["integrity"]),
        }

    def artifact(self, project_id: str, artifact_id: str) -> dict[str, Any]:
        project = self._project_for_update(project_id)
        business_gap_state = ensure_business_gap_state(project)
        plan = business_gap_state.get("plan") if isinstance(business_gap_state.get("plan"), dict) else {}
        for task in plan.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            for artifact in task.get("resolvedArtifacts") or []:
                if isinstance(artifact, dict) and str(artifact.get("artifactId") or "") == artifact_id:
                    return copy.deepcopy(artifact)
        raise KeyError(artifact_id)


business_gap_service = BusinessGapService()
