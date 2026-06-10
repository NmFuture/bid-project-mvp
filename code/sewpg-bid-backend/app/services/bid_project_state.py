from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

from app.services.bid_fill_state import default_fill_state
from app.services.bid_parse_state import default_parse_progress
from app.services.bid_runtime_state import build_directory_opencode_output, now_iso
from app.services.bid_type import BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE, require_bid_type
from app.services.file_utils import run_awaitable_sync
from app.services.identity import build_project_identity, build_project_material_scope
from app.services.peripheral import PeripheralError
from app.services.project_stage_flow import (
    STAGE_SCHEME,
    normalize_project_stage_value,
    project_progress_stages,
    project_stage_label,
    should_skip_technical_gap_stage,
    updated_project_stage_after_request,
)
from app.services.turbine_models import normalize_project_turbine_model, project_turbine_model
from app.services.workspace_artifacts import cleanup_parse_temp_workspace, promote_parse_artifacts_to_workspace


REVIEW_DECISION_LABELS = {
    "pending": "待审核",
    "participate": "参与投标",
    "abandon": "不参与",
}


def normalize_review_decision(value: Any, *, default: str = "pending") -> str:
    decision = str(value or default).strip().lower()
    if decision not in REVIEW_DECISION_LABELS:
        return default if default in REVIEW_DECISION_LABELS else "pending"
    return decision


def normalize_project_identity_state(project: dict[str, Any]) -> dict[str, Any]:
    project_id = str(project.get("id") or "")
    project["currentStage"] = normalize_project_stage_value(
        project.get("currentStage"),
        scheme=str(project.get("stageScheme") or ""),
    )
    project["stageScheme"] = STAGE_SCHEME
    project["projectCode"] = str(project.get("projectCode") or project_id)
    project["startDate"] = str(project.get("startDate") or "")
    project["endDate"] = str(project.get("endDate") or project.get("deadline") or "")
    project["deadline"] = str(project.get("deadline") or project.get("endDate") or "")
    identity = build_project_identity(project)
    project["identity"] = identity
    project["customerId"] = identity.get("customerId") or ""
    project["customerCanonicalName"] = identity.get("customerCanonicalName") or ""
    project["materialCustomerId"] = identity.get("customerId") or ""
    project["materialCustomerName"] = identity.get("customerCanonicalName") or ""
    project["materialProjectId"] = identity.get("projectId") or ""
    project["materialProjectCode"] = identity.get("projectCode") or ""
    project["materialProjectName"] = identity.get("projectName") or ""
    project["materialProjectMode"] = identity.get("materialProjectMode") or project.get("materialProjectMode") or ""
    turbine = project_turbine_model(project)
    project["turbineModel"] = turbine
    project["selectedTurbineModel"] = copy.deepcopy(turbine)
    project["turbineModelLabel"] = str(turbine.get("model") or "")
    return project


def project_summary_state(project: dict[str, Any]) -> dict[str, Any]:
    project = normalize_project_identity_state(project)
    if should_skip_technical_gap_stage(project) and int(project.get("currentStage") or 1) == 3:
        project["currentStage"] = 4
    identity = project.get("identity") or {}
    review_decision = normalize_review_decision(project.get("reviewDecision"), default="participate")
    stage_label = "审核终止" if review_decision == "abandon" else project_stage_label(project)
    turbine = project_turbine_model(project)
    return {
        "id": project["id"],
        "projectCode": project.get("projectCode") or project["id"],
        "name": project["name"],
        "customerName": project["customerName"],
        "customerId": identity.get("customerId") or "",
        "customerCanonicalName": identity.get("customerCanonicalName") or "",
        "customerAliases": copy.deepcopy(identity.get("customerAliases") or []),
        "materialCustomerId": project.get("materialCustomerId") or identity.get("customerId") or "",
        "materialCustomerName": project.get("materialCustomerName") or identity.get("customerCanonicalName") or "",
        "materialProjectId": project.get("materialProjectId") or identity.get("projectId") or "",
        "materialProjectCode": project.get("materialProjectCode") or identity.get("projectCode") or "",
        "materialProjectName": project.get("materialProjectName") or identity.get("projectName") or "",
        "materialProjectMode": project.get("materialProjectMode") or identity.get("materialProjectMode") or "",
        "turbineModel": copy.deepcopy(turbine),
        "selectedTurbineModel": copy.deepcopy(turbine),
        "turbineModelLabel": str(turbine.get("model") or ""),
        "owner": project["owner"],
        "manager": project["manager"],
        "startDate": project.get("startDate") or "",
        "endDate": project.get("endDate") or project.get("deadline") or "",
        "deadline": project.get("deadline") or project.get("endDate") or "",
        "bidType": project["bidType"],
        "currentStage": project["currentStage"],
        "stageLabel": stage_label,
        "reviewDecision": review_decision,
        "reviewDecisionLabel": REVIEW_DECISION_LABELS[review_decision],
        "reviewDecidedAt": project.get("reviewDecidedAt") or "",
        "updatedAt": project["updatedAt"],
        "identity": copy.deepcopy(identity),
    }


def project_detail_state(project: dict[str, Any]) -> dict[str, Any]:
    return {
        **project_summary_state(project),
        "files": copy.deepcopy(project["files"]),
        "templateFiles": copy.deepcopy(project["templateFiles"]),
        "templateFallback": copy.deepcopy(normalize_template_fallback_state(project)),
        "isKeyAccount": project["isKeyAccount"],
        "keyAccountId": project["keyAccountId"],
        "reviewComment": str(project.get("reviewComment") or ""),
    }


def project_list_state(
    projects: Iterable[dict[str, Any]],
    *,
    status: str = "",
    bid_type: str = "",
    review_decision: str = "",
    date_range: str = "",
    page: int = 1,
    page_size: int = 12,
) -> dict[str, Any]:
    items = [project_summary_state(project) for project in projects]
    normalized_bid_type = str(bid_type or "").strip()
    if normalized_bid_type:
        items = [item for item in items if str(item.get("bidType") or "").strip() == normalized_bid_type]
    normalized_review_decision = str(review_decision or "").strip().lower()
    if normalized_review_decision:
        items = [
            item
            for item in items
            if str(item.get("reviewDecision") or "").strip().lower() == normalized_review_decision
        ]
    items.sort(key=lambda item: item["updatedAt"], reverse=True)
    start = max(0, (page - 1) * page_size)
    end = start + page_size
    return {
        "items": items[start:end],
        "total": len(items),
        "page": page,
        "pageSize": page_size,
    }


def project_stages_state(project: dict[str, Any]) -> list[dict[str, Any]]:
    return project_progress_stages(project)


def normalize_template_fallback_state(project: dict[str, Any]) -> dict[str, Any]:
    raw = project.get("templateFallback")
    fallback = raw if isinstance(raw, dict) else {}
    enabled = fallback.get("enabled")
    if enabled is None:
        enabled = True
    return {
        "enabled": bool(enabled),
        "sourceId": str(fallback.get("sourceId") or "system-default"),
    }


def project_bid_type(project: dict[str, Any]) -> str:
    return require_bid_type(
        project.get("bidType"),
        error_message="项目状态必须显式传入技术标或商务标。",
    )


def project_parse_input_records(
    project_id: str,
    project: dict[str, Any],
    *,
    include_fallback: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    template_file_records = copy.deepcopy(project.get("templateFileRecords") or [])
    if include_fallback and not template_file_records and normalize_template_fallback_state(project)["enabled"]:
        from app.services import template_store as template_store_module

        fallback_record = template_store_module.resolve_fallback_bid_template_file_sync(
            project_id,
            project_bid_type(project),
        )
        if fallback_record is not None:
            template_file_records = [fallback_record]
    return (
        copy.deepcopy(project.get("fileRecords") or []),
        template_file_records,
    )


def project_template_fallback_context(project_id: str, project: dict[str, Any]) -> dict[str, Any]:
    current = normalize_template_fallback_state(project)
    return {
        "projectId": project_id,
        "bidType": project_bid_type(project),
        "enabled": bool(current["enabled"]),
        "sourceId": str(current["sourceId"]),
        "hasProjectTemplate": bool(project.get("templateFileRecords")),
    }


def project_template_fallback_payload(project_id: str, project: dict[str, Any]) -> dict[str, Any]:
    from app.services.template_store import template_fallback_payload

    context = project_template_fallback_context(project_id, project)
    payload = template_fallback_payload(
        project_id=project_id,
        bid_type=str(context["bidType"]),
        enabled=bool(context["enabled"]),
        source_id=str(context["sourceId"]),
        has_project_template=bool(context["hasProjectTemplate"]),
    )
    result = run_awaitable_sync(payload)
    return result if isinstance(result, dict) else {}


def update_template_fallback_state(project: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    current = normalize_template_fallback_state(project)
    if "enabled" in data:
        current["enabled"] = bool(data.get("enabled"))
    if "sourceId" in data:
        current["sourceId"] = str(data.get("sourceId") or "system-default")
    project["templateFallback"] = current
    project["updatedAt"] = now_iso()
    return current


def update_stage_state(project: dict[str, Any], stage: int, data: dict[str, Any]) -> dict[str, Any]:
    status = str(data.get("status") or "").strip()
    project["currentStage"] = updated_project_stage_after_request(project, stage, status)
    project["stageScheme"] = STAGE_SCHEME
    project["updatedAt"] = now_iso()
    return {
        "message": "阶段状态已更新",
        "currentStage": project["currentStage"],
        "stageLabel": project_stage_label(project),
    }


def create_project_state(project_id: str, data: dict[str, Any]) -> dict[str, Any]:
    bid_type = require_bid_type(
        data.get("bidType"),
        error_message="新建项目必须显式传入技术标或商务标。",
    )
    project_name = str(data.get("name") or project_id)
    review_decision = normalize_review_decision(data.get("reviewDecision"))
    created_at = now_iso()
    return {
        "id": project_id,
        "projectCode": str(data.get("projectCode") or project_id),
        "name": project_name,
        "customerName": str(data.get("customerName") or ""),
        "customerId": str(data.get("customerId") or ""),
        "customerCanonicalName": str(data.get("customerCanonicalName") or ""),
        "materialCustomerId": str(data.get("materialCustomerId") or data.get("customerId") or ""),
        "materialCustomerName": str(data.get("materialCustomerName") or data.get("customerCanonicalName") or data.get("customerName") or ""),
        "materialProjectMode": str(data.get("materialProjectMode") or ""),
        "materialProjectId": str(data.get("materialProjectId") or ""),
        "materialProjectCode": str(data.get("materialProjectCode") or ""),
        "materialProjectName": str(data.get("materialProjectName") or data.get("name") or ""),
        "owner": str(data.get("owner") or data.get("customerName") or ""),
        "manager": str(data.get("manager") or ""),
        "startDate": str(data.get("startDate") or ""),
        "endDate": str(data.get("endDate") or data.get("deadline") or ""),
        "deadline": str(data.get("deadline") or data.get("endDate") or ""),
        "bidType": bid_type,
        "turbineModel": normalize_project_turbine_model(
            data.get("turbineModel") or data.get("selectedTurbineModel") or data.get("machineModel")
        ),
        "isKeyAccount": bool(data.get("isKeyAccount")),
        "keyAccountId": str(data.get("keyAccountId") or ""),
        "reviewDecision": review_decision,
        "reviewDecidedAt": created_at if review_decision in {"participate", "abandon"} else "",
        "reviewComment": str(data.get("reviewComment") or ""),
        "files": [],
        "templateFiles": [],
        "fileRecords": [],
        "templateFileRecords": [],
        "templateFallback": {
            "enabled": True,
            "sourceId": "system-default",
        },
        "stageScheme": STAGE_SCHEME,
        "currentStage": 1,
        "updatedAt": created_at,
        "parse_result": default_parse_result_state(),
        "parse_storage": default_parse_storage_state(),
        "parse_progress": default_parse_progress(),
        "directory_state": default_directory_state(),
        "outline_state": default_outline_state(),
        "fill_state": default_fill_state({"bidType": bid_type}),
        "document_state": default_document_state(project_id, project_name),
        "gap_state": default_technical_gap_state(),
        "business_gap_state": default_business_gap_state(),
        "review_document_state": default_review_document_state(project_id, project_name),
    }


def update_project_state(project: dict[str, Any], project_id: str, data: dict[str, Any]) -> dict[str, Any]:
    for field in [
        "name",
        "projectCode",
        "customerName",
        "customerId",
        "customerCanonicalName",
        "materialCustomerId",
        "materialCustomerName",
        "materialProjectMode",
        "materialProjectId",
        "materialProjectCode",
        "materialProjectName",
        "owner",
        "manager",
        "startDate",
        "endDate",
        "deadline",
    ]:
        if field in data:
            project[field] = str(data[field] or "") if field == "projectCode" else data[field]
    if "bidType" in data:
        project["bidType"] = require_bid_type(
            data.get("bidType"),
            error_message="更新项目必须显式传入技术标或商务标。",
        )
    if any(field in data for field in ("turbineModel", "selectedTurbineModel", "machineModel")):
        project["turbineModel"] = normalize_project_turbine_model(
            data.get("turbineModel") or data.get("selectedTurbineModel") or data.get("machineModel")
        )
    if "endDate" in data and "deadline" not in data:
        project["deadline"] = str(data.get("endDate") or "")
    if "deadline" in data and "endDate" not in data:
        project["endDate"] = str(data.get("deadline") or "")
    if "reviewDecision" in data:
        update_review_decision_state(project, project_id, data.get("reviewDecision"))
    if "reviewComment" in data:
        project["reviewComment"] = str(data.get("reviewComment") or "")
    project["updatedAt"] = now_iso()
    return project


def update_review_decision_state(project: dict[str, Any], project_id: str, value: Any) -> None:
    decision = normalize_review_decision(value)
    project["reviewDecision"] = decision
    project["reviewDecidedAt"] = now_iso() if decision in {"participate", "abandon"} else ""
    if decision == "participate":
        parse_result = project.get("parse_result") if isinstance(project.get("parse_result"), dict) else {}
        parse_storage = project.get("parse_storage") if isinstance(project.get("parse_storage"), dict) else {}
        if parse_result.get("status") == "completed":
            promoted = promote_parse_artifacts_to_workspace(
                project_id,
                parse_result,
                parse_storage,
                bid_type=project_bid_type(project),
            )
            project["parse_result"] = promoted["parseResult"]
            project["parse_storage"] = promoted["parseStorage"]
            if promoted["stageArtifacts"]:
                project["stageArtifacts"] = promoted["stageArtifacts"]
            project["workspaceArtifacts"] = promoted["artifacts"]
            cleanup_parse_temp_workspace(project_id)
    elif decision == "abandon":
        cleanup_parse_temp_workspace(project_id)


def delete_project_side_effects(project_id: str, project: dict[str, Any]) -> None:
    cleanup_parse_temp_workspace(project_id)
    delete_project_material_folder(project)


def delete_project_material_folder(project: dict[str, Any]) -> None:
    scope = build_project_material_scope(project)
    for item in scope.get("readableScopes") or []:
        if str(item.get("key") or "") != "project":
            continue
        path = str(item.get("path") or "").strip().strip("/")
        if not path or not (
            path.startswith(f"{BUSINESS_BID_TYPE}/项目素材/")
            or path.startswith(f"{TECHNICAL_BID_TYPE}/项目素材/")
        ):
            continue
        try:
            run_workspace_material_folder_delete(path)
        except PeripheralError as exc:
            if exc.code == "RAW_FOLDER_NOT_FOUND":
                return
            raise
        return


def run_workspace_material_folder_delete(path: str) -> dict[str, Any]:
    normalized = str(path or "").strip().strip("/")
    if normalized.startswith(f"{BUSINESS_BID_TYPE}/"):
        from app.services.business_material_store import business_material_store

        result = run_awaitable_sync(business_material_store.raw_cleanup_project_folder(normalized))
    elif normalized.startswith(f"{TECHNICAL_BID_TYPE}/"):
        from app.services.technical_material_store import technical_material_store

        result = run_awaitable_sync(technical_material_store.raw_cleanup_project_folder(normalized))
    else:
        raise PeripheralError(400, "项目素材目录必须位于技术标或商务标素材库。", "PROJECT_MATERIAL_PATH_REQUIRED")
    return result if isinstance(result, dict) else {}


def default_parse_result_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "parsedAt": "",
        "sourceFiles": [],
        "items": [],
        "summary": {
            "fileCount": 0,
            "extractedCount": 0,
            "textLength": 0,
            "textPreview": "",
            "warnings": [],
        },
    }


def default_parse_storage_state() -> dict[str, Any]:
    return {
        "projectDir": "",
        "combinedTextPath": "",
        "manifestPath": "",
        "documents": [],
    }


def default_directory_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "percentage": 0,
        "summary": "尚未生成目录。",
        "generatedAt": "",
        "output": None,
        "opencodeOutput": build_directory_opencode_output(),
        "events": [],
        "tasks": [
            {"id": "task-1", "label": "准备目录候选", "status": "pending"},
            {"id": "task-2", "label": "futurecode 语义审核", "status": "pending"},
            {"id": "task-3", "label": "保存审核目录", "status": "pending"},
        ],
    }


def default_outline_state() -> dict[str, Any]:
    return {
        "outlineVersion": 1,
        "reviewStatus": "draft",
        "generatedAt": "",
        "summary": {"totalNodeCount": 0},
        "nodes": [],
    }


def default_document_state(project_id: str, project_name: str) -> dict[str, Any]:
    file_name = f"{project_name}_正文.docx"
    return {
        "status": "ready",
        "documentId": f"DOC-{project_id}",
        "sourceFileName": file_name,
        "fileName": file_name,
        "fileType": "docx",
        "version": 1,
        "lastSavedAt": "",
        "onlyoffice": {
            "documentKey": f"{project_id}-v1",
            "title": file_name,
            "user": {"id": "user-1", "name": "当前用户"},
        },
        "fallback": {
            "content": "OnlyOffice 未接入前，这里先展示后端生成的占位文档内容。",
        },
    }


def default_technical_gap_state() -> dict[str, Any]:
    return {
        "recognitionStatus": "idle",
        "recognizedAt": "",
        "submittedForReview": False,
        "reviewConfirmed": False,
        "reviewedAt": "",
        "items": [],
        "submissions": [],
        "plan": {},
        "planFile": "",
        "integrity": {},
        "projectFactTable": {},
    }


def default_business_gap_state() -> dict[str, Any]:
    return {
        "recognitionStatus": "idle",
        "recognizedAt": "",
        "submittedForReview": False,
        "reviewConfirmed": False,
        "reviewedAt": "",
        "plan": {},
        "planFile": "",
        "integrity": {},
    }


def default_review_document_state(project_id: str, project_name: str) -> dict[str, Any]:
    return {
        "parseStatus": "idle",
        "parsedAt": "",
        "documentId": f"REV-DOC-{project_id}",
        "sourceFileName": "",
        "fileName": f"{project_name}_缺口处理确认预览.docx",
        "fileType": "docx",
        "content": "",
        "lastSavedAt": "",
        "version": 1,
        "documentKey": f"{project_id}-s6-v1",
    }
