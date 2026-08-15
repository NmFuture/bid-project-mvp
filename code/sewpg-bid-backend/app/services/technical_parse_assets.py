from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from app.services.bid_parse_state import update_parse_result_state
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.file_utils import safe_segment
from app.services.identity import build_project_material_scope
from app.services.onlyoffice_documents import WORD_MEDIA_TYPE
from app.services.technical_material_index import rebuild_technical_material_index_strict
from app.services.technical_material_store import technical_material_store
from app.services.workspace_project_access import (
    mutate_workspace_project,
)


TECHNICAL_APPENDIX_SYNC_SCHEMA_VERSION = "technical-appendix-material-sync-v1"


class TechnicalParseAssetError(RuntimeError):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class TechnicalParseAssetSyncSuperseded(RuntimeError):
    """后台任务使用的解析结果或附表选择已过期。"""


def _stable_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def technical_parse_revision(parse_result: dict[str, Any]) -> str:
    explicit = str(parse_result.get("parseRevision") or "").strip()
    if explicit:
        return explicit

    # 兼容修复上线前的历史解析结果：排除仅由素材同步/勾选维护的字段，
    # 其余解析内容生成稳定指纹，用于识别任务期间发生的重新解析。
    comparable = copy.deepcopy(parse_result)
    comparable.pop("appendixSelectionRevision", None)
    structured = comparable.get("structured") if isinstance(comparable.get("structured"), dict) else {}
    structured.pop("technicalAppendixMaterialSync", None)
    appendices = structured.get("appendices") if isinstance(structured.get("appendices"), list) else []
    for appendix in appendices:
        if not isinstance(appendix, dict):
            continue
        appendix.pop("selectedForMaterial", None)
        appendix.pop("assetMaterialId", None)
        appendix.pop("assetSyncStatus", None)
    comparable["structured"] = structured
    return f"legacy:{_stable_digest(comparable)}"


def technical_appendix_selection_revision(parse_result: dict[str, Any]) -> str:
    if "appendixSelectionRevision" in parse_result:
        try:
            return f"revision:{int(parse_result.get('appendixSelectionRevision') or 0)}"
        except (TypeError, ValueError):
            pass
    structured = parse_result.get("structured") if isinstance(parse_result.get("structured"), dict) else {}
    appendices = structured.get("appendices") if isinstance(structured.get("appendices"), list) else []
    selection = [
        {
            "id": str(item.get("id") or ""),
            "selected": item.get("selectedForMaterial") is True,
        }
        for item in appendices
        if isinstance(item, dict)
    ]
    return f"legacy:{_stable_digest(selection)}"


def technical_parse_sync_versions(parse_result: dict[str, Any]) -> tuple[str, str]:
    return technical_parse_revision(parse_result), technical_appendix_selection_revision(parse_result)


def _technical_parse_selection_payload(
    project: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    parse_result = copy.deepcopy(project.get("parse_result") if isinstance(project.get("parse_result"), dict) else {})
    if parse_result.get("status") != "completed":
        raise TechnicalParseAssetError("请先完成技术标解析。")
    structured = parse_result.get("structured") if isinstance(parse_result.get("structured"), dict) else {}
    appendices = structured.get("appendices") if isinstance(structured.get("appendices"), list) else []
    return parse_result, [item for item in appendices if isinstance(item, dict)]


def _store_selection(project: dict[str, Any], parse_result: dict[str, Any]) -> dict[str, Any]:
    try:
        current_revision = int(parse_result.get("appendixSelectionRevision") or 0)
    except (TypeError, ValueError):
        current_revision = 0
    parse_result["appendixSelectionRevision"] = current_revision + 1
    parse_storage = copy.deepcopy(project.get("parse_storage") if isinstance(project.get("parse_storage"), dict) else {})
    parse_storage["items"] = copy.deepcopy(parse_result.get("items") or parse_storage.get("items") or [])
    parse_storage["structured"] = copy.deepcopy(parse_result.get("structured") or {})
    return update_parse_result_state(project, parse_result, parse_storage=parse_storage)


def set_technical_appendix_asset_selected(
    project_id: str,
    appendix_id: str,
    *,
    selected: bool,
) -> dict[str, Any]:
    def apply(project: dict[str, Any]) -> dict[str, Any]:
        parse_result, appendices = _technical_parse_selection_payload(project)
        target = next((item for item in appendices if str(item.get("id") or "") == appendix_id), None)
        if target is None:
            raise TechnicalParseAssetError("未找到对应的技术标附表。", 404)
        target["selectedForMaterial"] = bool(selected)
        parse_result["structured"]["appendices"] = appendices
        persisted = _store_selection(project, parse_result)
        selected_count = sum(item.get("selectedForMaterial") is True for item in appendices)
        return {
            "message": "已更新附表素材选择。",
            "selectedCount": selected_count,
            "appendixCount": len(appendices),
            "parseResult": persisted,
        }

    return mutate_workspace_project(
        project_id,
        apply,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=KeyError,
        wrong_type_error=lambda _project_id: TechnicalParseAssetError("仅技术标解析附表支持该操作。"),
    )


def set_all_technical_appendix_assets_selected(project_id: str, *, selected: bool) -> dict[str, Any]:
    def apply(project: dict[str, Any]) -> dict[str, Any]:
        parse_result, appendices = _technical_parse_selection_payload(project)
        for appendix in appendices:
            appendix["selectedForMaterial"] = bool(selected)
        parse_result["structured"]["appendices"] = appendices
        persisted = _store_selection(project, parse_result)
        return {
            "message": "已全选附表。" if selected else "已清空附表选择。",
            "selectedCount": len(appendices) if selected else 0,
            "appendixCount": len(appendices),
            "parseResult": persisted,
        }

    return mutate_workspace_project(
        project_id,
        apply,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=KeyError,
        wrong_type_error=lambda _project_id: TechnicalParseAssetError("仅技术标解析附表支持该操作。"),
    )


def _merge_appendix_sync_fields(
    target_structured: dict[str, Any],
    synced_structured: dict[str, Any],
) -> dict[str, Any]:
    merged = copy.deepcopy(target_structured)
    synced_appendices = (
        synced_structured.get("appendices")
        if isinstance(synced_structured.get("appendices"), list)
        else []
    )
    synced_by_id = {
        str(item.get("id") or ""): item
        for item in synced_appendices
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    appendices = merged.get("appendices") if isinstance(merged.get("appendices"), list) else []
    for appendix in appendices:
        if not isinstance(appendix, dict):
            continue
        synced = synced_by_id.get(str(appendix.get("id") or ""), {})
        for field in ("assetMaterialId", "assetSyncStatus"):
            if field in synced:
                appendix[field] = copy.deepcopy(synced[field])
            else:
                appendix.pop(field, None)
    merged["appendices"] = appendices
    if "technicalAppendixMaterialSync" in synced_structured:
        merged["technicalAppendixMaterialSync"] = copy.deepcopy(
            synced_structured["technicalAppendixMaterialSync"]
        )
    return merged


def persist_technical_parse_asset_sync_result(
    project_id: str,
    synced_parse_result: dict[str, Any],
    *,
    expected_parse_revision: str,
    expected_selection_revision: str,
) -> dict[str, Any]:
    """只把附表同步字段合入最新解析结果，CAS 冲突时基于最新项目重放。"""

    def apply(project: dict[str, Any]) -> dict[str, Any]:
        current = copy.deepcopy(
            project.get("parse_result") if isinstance(project.get("parse_result"), dict) else {}
        )
        current_versions = technical_parse_sync_versions(current)
        if current_versions != (expected_parse_revision, expected_selection_revision):
            raise TechnicalParseAssetSyncSuperseded("解析结果或附表选择已更新，本次后台同步结果未覆盖保存。")

        current_structured = (
            current.get("structured") if isinstance(current.get("structured"), dict) else {}
        )
        synced_structured = (
            synced_parse_result.get("structured")
            if isinstance(synced_parse_result.get("structured"), dict)
            else {}
        )
        merged_structured = _merge_appendix_sync_fields(current_structured, synced_structured)
        current["structured"] = merged_structured

        parse_storage = copy.deepcopy(
            project.get("parse_storage") if isinstance(project.get("parse_storage"), dict) else {}
        )
        storage_structured = (
            parse_storage.get("structured")
            if isinstance(parse_storage.get("structured"), dict)
            else {}
        )
        storage_structured = copy.deepcopy(storage_structured)
        storage_structured["appendices"] = copy.deepcopy(merged_structured.get("appendices") or [])
        if "technicalAppendixMaterialSync" in merged_structured:
            storage_structured["technicalAppendixMaterialSync"] = copy.deepcopy(
                merged_structured["technicalAppendixMaterialSync"]
            )
        parse_storage["structured"] = storage_structured
        return update_parse_result_state(project, current, parse_storage=parse_storage)

    return mutate_workspace_project(
        project_id,
        apply,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=KeyError,
        wrong_type_error=lambda _project_id: TechnicalParseAssetError("仅技术标解析附表支持该操作。"),
    )


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
    *,
    ensure_current: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """让项目素材库中的解析附表与最后一次勾选结果保持一致。"""

    if str(project.get("bidType") or "") != TECHNICAL_BID_TYPE:
        raise TechnicalParseAssetError("仅技术标解析附表支持该同步操作。")
    if ensure_current is not None:
        ensure_current()

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

    project_scope = next(
        (item for item in material_scope["readableScopes"] if item.get("key") == "project"),
        {},
    )
    project_path = str(project_scope.get("path") or "").strip()
    if not project_path:
        raise TechnicalParseAssetError("项目名称为空，无法同步技术标附表。")
    target_path = f"{project_path}/附表"
    uploaded_items: list[dict[str, Any]] = []
    if files:
        result = await technical_material_store.raw_upload(
            target_path=target_path,
            project_id=material_project_id,
            project_code=str(identity.get("projectCode") or material_project_id),
            project_name=str(identity.get("projectName") or project.get("name") or ""),
            material_tier="project",
            customer_id=str(identity.get("customerId") or ""),
            customer_name=str(identity.get("customerCanonicalName") or identity.get("customerName") or ""),
            on_conflict="overwrite",
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

    # 上传是幂等覆盖，但删除不可逆。删除旧素材前必须再读一次当前版本，
    # 避免任务运行期间新勾选的附表被旧快照当成过期文件删除。
    if ensure_current is not None:
        ensure_current()
    delete_result = {"succeeded": [], "failed": []}
    if stale_material_ids:
        delete_result = await technical_material_store.raw_batch_delete_files(stale_material_ids)
    if ensure_current is not None:
        ensure_current()
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
