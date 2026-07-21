from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from app.services.bid_parse_state import update_parse_result_state
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.file_utils import safe_segment
from app.services.identity import build_project_material_scope
from app.services.onlyoffice_documents import WORD_MEDIA_TYPE
from app.services.technical_material_index import rebuild_technical_material_index_strict
from app.services.technical_material_store import technical_material_store
from app.services.workspace_project_access import (
    persist_workspace_project_state,
    require_workspace_project_for_update,
)


TECHNICAL_APPENDIX_SYNC_SCHEMA_VERSION = "technical-appendix-material-sync-v1"


class TechnicalParseAssetError(RuntimeError):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def persist_technical_parse_result(project_id: str, parse_result: dict[str, Any]) -> dict[str, Any]:
    project = require_workspace_project_for_update(
        project_id,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=KeyError,
        wrong_type_error=lambda _project_id: TechnicalParseAssetError("仅技术标解析附表支持该操作。"),
    )
    parse_storage = copy.deepcopy(project.get("parse_storage") if isinstance(project.get("parse_storage"), dict) else {})
    parse_storage["items"] = copy.deepcopy(parse_result.get("items") or parse_storage.get("items") or [])
    parse_storage["structured"] = copy.deepcopy(parse_result.get("structured") or {})
    payload = update_parse_result_state(project, parse_result, parse_storage=parse_storage)
    persist_workspace_project_state(project)
    return payload


def _technical_parse_selection_payload(
    project_id: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    project = require_workspace_project_for_update(
        project_id,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=KeyError,
        wrong_type_error=lambda _project_id: TechnicalParseAssetError("仅技术标解析附表支持该操作。"),
    )
    parse_result = copy.deepcopy(project.get("parse_result") if isinstance(project.get("parse_result"), dict) else {})
    if parse_result.get("status") != "completed":
        raise TechnicalParseAssetError("请先完成技术标解析。")
    structured = parse_result.get("structured") if isinstance(parse_result.get("structured"), dict) else {}
    appendices = structured.get("appendices") if isinstance(structured.get("appendices"), list) else []
    return project, parse_result, [item for item in appendices if isinstance(item, dict)]


def _persist_selection(project: dict[str, Any], parse_result: dict[str, Any]) -> dict[str, Any]:
    parse_storage = copy.deepcopy(project.get("parse_storage") if isinstance(project.get("parse_storage"), dict) else {})
    parse_storage["items"] = copy.deepcopy(parse_result.get("items") or parse_storage.get("items") or [])
    parse_storage["structured"] = copy.deepcopy(parse_result.get("structured") or {})
    payload = update_parse_result_state(project, parse_result, parse_storage=parse_storage)
    persist_workspace_project_state(project)
    return payload


def set_technical_appendix_asset_selected(
    project_id: str,
    appendix_id: str,
    *,
    selected: bool,
) -> dict[str, Any]:
    project, parse_result, appendices = _technical_parse_selection_payload(project_id)
    target = next((item for item in appendices if str(item.get("id") or "") == appendix_id), None)
    if target is None:
        raise TechnicalParseAssetError("未找到对应的技术标附表。", 404)
    target["selectedForMaterial"] = bool(selected)
    parse_result["structured"]["appendices"] = appendices
    persisted = _persist_selection(project, parse_result)
    selected_count = sum(item.get("selectedForMaterial") is True for item in appendices)
    return {
        "message": "已更新附表素材选择。",
        "selectedCount": selected_count,
        "appendixCount": len(appendices),
        "parseResult": persisted,
    }


def set_all_technical_appendix_assets_selected(project_id: str, *, selected: bool) -> dict[str, Any]:
    project, parse_result, appendices = _technical_parse_selection_payload(project_id)
    for appendix in appendices:
        appendix["selectedForMaterial"] = bool(selected)
    parse_result["structured"]["appendices"] = appendices
    persisted = _persist_selection(project, parse_result)
    return {
        "message": "已全选附表。" if selected else "已清空附表选择。",
        "selectedCount": len(appendices) if selected else 0,
        "appendixCount": len(appendices),
        "parseResult": persisted,
    }


def _appendix_material_name(title: str) -> str:
    clean_title = safe_segment(title, "附表")
    stem = Path(clean_title).stem if clean_title.lower().endswith(".docx") else clean_title
    if not stem.startswith("待填写-"):
        stem = f"待填写-{stem}"
    return f"{stem}.docx"


def _appendix_material_file(appendix: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(appendix.get("docxPath") or ""))
    if not path.exists() or not path.is_file():
        title = str(appendix.get("title") or appendix.get("id") or "附表")
        raise TechnicalParseAssetError(f"附表 Word 文件不存在：{title}")
    title = str(appendix.get("title") or path.stem or "附表").strip()
    return {
        "name": _appendix_material_name(title),
        "type": WORD_MEDIA_TYPE,
        "mimeType": WORD_MEDIA_TYPE,
        "data": path.read_bytes(),
        "relativePath": "",
    }


def _indexed_file_ids(payload: dict[str, Any]) -> set[str]:
    return {
        str(file_item.get("id") or "")
        for tier in payload.get("tiers") or []
        for folder in tier.get("folders") or []
        for file_item in folder.get("files") or []
        if str(file_item.get("id") or "")
    }


async def sync_technical_parse_appendices(
    project: dict[str, Any],
    parse_result: dict[str, Any],
) -> dict[str, Any]:
    """让项目素材库中的解析附表与最后一次勾选结果保持一致。"""

    if str(project.get("bidType") or "") != TECHNICAL_BID_TYPE:
        raise TechnicalParseAssetError("仅技术标解析附表支持该同步操作。")

    structured = parse_result.get("structured") if isinstance(parse_result.get("structured"), dict) else {}
    appendices = structured.get("appendices") if isinstance(structured.get("appendices"), list) else []
    selected_appendices = [
        item
        for item in appendices
        if isinstance(item, dict) and item.get("selectedForMaterial") is True and str(item.get("id") or "")
    ]
    sync_state = (
        structured.get("technicalAppendixMaterialSync")
        if isinstance(structured.get("technicalAppendixMaterialSync"), dict)
        else {}
    )
    previous_items = [item for item in sync_state.get("items") or [] if isinstance(item, dict)]
    previous_by_appendix_id = {
        str(item.get("appendixId") or ""): item
        for item in previous_items
        if str(item.get("appendixId") or "") and str(item.get("materialId") or "")
    }
    pending_delete_ids = [str(item) for item in sync_state.get("pendingDeleteIds") or [] if str(item)]
    tracked_material_ids = {
        str(item.get("materialId") or "") for item in previous_by_appendix_id.values()
    } | set(pending_delete_ids)
    existing_material_ids: set[str] = set()
    if tracked_material_ids:
        current_index = await rebuild_technical_material_index_strict()
        existing_material_ids = _indexed_file_ids(current_index)
    selected_ids = {str(item.get("id") or "") for item in selected_appendices}
    retained_items = {
        appendix_id: copy.deepcopy(item)
        for appendix_id, item in previous_by_appendix_id.items()
        if appendix_id in selected_ids and str(item.get("materialId") or "") in existing_material_ids
    }
    upload_appendices = [
        item for item in selected_appendices if str(item.get("id") or "") not in retained_items
    ]
    files = [_appendix_material_file(item) for item in upload_appendices]
    stale_material_ids = list(
        dict.fromkeys(
            [
                str(item.get("materialId") or "")
                for appendix_id, item in previous_by_appendix_id.items()
                if appendix_id not in selected_ids
                and str(item.get("materialId") or "") in existing_material_ids
            ]
            + [item for item in pending_delete_ids if item in existing_material_ids]
        )
    )
    stale_material_ids = [item for item in stale_material_ids if item]
    if not selected_appendices and not stale_material_ids:
        structured["technicalAppendixMaterialSync"] = {
            "schemaVersion": TECHNICAL_APPENDIX_SYNC_SCHEMA_VERSION,
            "items": [],
            "pendingDeleteIds": [],
        }
        parse_result["structured"] = structured
        return {
            "status": "skipped",
            "syncedCount": 0,
            "selectedCount": 0,
            "uploadedCount": 0,
            "deletedCount": 0,
            "items": [],
        }

    material_scope = build_project_material_scope(project)
    identity = material_scope["identity"]
    material_project_id = str(identity.get("projectId") or "").strip()
    if not material_project_id:
        raise TechnicalParseAssetError("项目素材 ID 为空，无法同步技术标附表。")

    project_name = str(project.get("name") or identity.get("bidProjectName") or "").strip()
    project_scope = next(
        (item for item in material_scope["readableScopes"] if item.get("key") == "project"),
        {},
    )
    target_path = str(project_scope.get("path") or "").strip()
    uploaded_items: list[dict[str, Any]] = []
    if files:
        await technical_material_store.raw_bootstrap_folders(material_project_id, project_name)
        result = await technical_material_store.raw_upload(
            target_path=target_path,
            project_id=material_project_id,
            project_code=str(identity.get("projectCode") or material_project_id),
            project_name=str(identity.get("projectName") or project.get("name") or ""),
            material_tier="project",
            customer_id=str(identity.get("customerId") or ""),
            customer_name=str(identity.get("customerCanonicalName") or identity.get("customerName") or ""),
            on_conflict="",
            files=files,
        )
        uploaded_items = [item for item in result.get("items") or [] if isinstance(item, dict)]
        if len(uploaded_items) != len(files):
            raise TechnicalParseAssetError("技术标附表未全部写入项目素材库。")

    uploaded_by_appendix_id: dict[str, dict[str, Any]] = {}
    for appendix, uploaded_item in zip(upload_appendices, uploaded_items, strict=False):
        appendix_id = str(appendix.get("id") or "")
        uploaded_by_appendix_id[appendix_id] = {
            "appendixId": appendix_id,
            "materialId": str(uploaded_item.get("id") or ""),
            "name": str(uploaded_item.get("name") or ""),
        }

    delete_result = {"succeeded": [], "failed": []}
    if stale_material_ids:
        delete_result = await technical_material_store.raw_batch_delete_files(stale_material_ids)
    deleted_ids = {str(item) for item in delete_result.get("succeeded") or []}
    failed_delete_ids = [
        str(item.get("fileId") or "")
        for item in delete_result.get("failed") or []
        if isinstance(item, dict) and str(item.get("fileId") or "")
    ]

    current_items: list[dict[str, Any]] = []
    for appendix in selected_appendices:
        appendix_id = str(appendix.get("id") or "")
        sync_item = uploaded_by_appendix_id.get(appendix_id) or retained_items.get(appendix_id)
        if not isinstance(sync_item, dict):
            continue
        normalized_item = {
            "appendixId": appendix_id,
            "materialId": str(sync_item.get("materialId") or ""),
            "name": str(sync_item.get("name") or ""),
        }
        current_items.append(normalized_item)
        appendix["assetMaterialId"] = normalized_item["materialId"]
        appendix["assetSyncStatus"] = "synced"
    for appendix in appendices:
        if not isinstance(appendix, dict) or appendix.get("selectedForMaterial") is True:
            continue
        appendix.pop("assetMaterialId", None)
        appendix.pop("assetSyncStatus", None)

    structured["technicalAppendixMaterialSync"] = {
        "schemaVersion": TECHNICAL_APPENDIX_SYNC_SCHEMA_VERSION,
        "items": current_items,
        "pendingDeleteIds": failed_delete_ids,
    }
    parse_result["structured"] = structured

    index_payload = await rebuild_technical_material_index_strict()
    missing_ids = {
        str(item.get("materialId") or "")
        for item in current_items
        if str(item.get("materialId") or "") not in _indexed_file_ids(index_payload)
    }
    if missing_ids:
        raise TechnicalParseAssetError("技术标附表同步后，全局素材目录未包含全部已选文件。")

    return {
        "status": "partial" if failed_delete_ids else "synced",
        "syncedCount": len(current_items),
        "selectedCount": len(selected_appendices),
        "uploadedCount": len(uploaded_items),
        "retainedCount": len(retained_items),
        "deletedCount": len(deleted_ids),
        "failedDeleteCount": len(failed_delete_ids),
        "items": current_items,
        "targetPath": target_path,
    }
