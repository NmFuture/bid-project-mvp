from __future__ import annotations

import copy
import mimetypes
from pathlib import Path
from typing import Any

from app.services.business_gap_planning import build_business_gap_material_picker_index
from app.services.business_material_store import business_material_store
from app.services.file_utils import run_awaitable_sync, safe_filename
from app.services.minio_client import minio_client


def business_table_fill_source_materials(project: dict[str, Any], data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_sources = data.get("sourceMaterials")
    if raw_sources is None:
        raw_sources = data.get("materials") or data.get("sourceMaterialIds") or data.get("materialIds") or []
    entries = raw_sources if isinstance(raw_sources, list) else []
    picker = build_business_gap_material_picker_index(project)
    index = {
        str(item.get("id") or item.get("materialId") or ""): item
        for item in picker.get("materialIndex") or []
        if isinstance(item, dict) and str(item.get("id") or item.get("materialId") or "")
    }
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        if isinstance(entry, str):
            material_id = entry
            item = copy.deepcopy(index.get(material_id) or {"id": material_id, "materialId": material_id})
        elif isinstance(entry, dict):
            material_id = str(entry.get("id") or entry.get("materialId") or "").strip()
            item = {**copy.deepcopy(index.get(material_id) or {}), **copy.deepcopy(entry)}
        else:
            continue
        material_id = str(item.get("id") or item.get("materialId") or "").strip()
        if not material_id or material_id in seen:
            continue
        seen.add(material_id)
        item["id"] = material_id
        item["materialId"] = material_id
        item["materialName"] = str(item.get("materialName") or item.get("name") or item.get("fileName") or material_id)
        if not str(item.get("businessMaterialKind") or ""):
            item["businessMaterialKind"] = str((index.get(material_id) or {}).get("businessMaterialKind") or "")
        if not str(item.get("businessMaterialKindLabel") or ""):
            item["businessMaterialKindLabel"] = str((index.get(material_id) or {}).get("businessMaterialKindLabel") or "")
        result.append(item)
    return result


def prepare_business_table_fill_target(target: dict[str, Any], work_dir: Path) -> dict[str, Any]:
    item = copy.deepcopy(target)
    for key in ("filePath", "path", "docxPath", "workspacePath"):
        value = str(item.get(key) or "").strip()
        if value and Path(value).exists():
            return item
    file_name = str(item.get("fileName") or "").strip()
    if file_name and len(work_dir.parents) >= 3:
        workspace_root = work_dir.parents[2]
        for subdir in ("appendices", "commitment-letters"):
            candidate = workspace_root / subdir / file_name
            if candidate.exists():
                item.update({"filePath": str(candidate), "path": str(candidate), "fileName": candidate.name})
                return item
    material_id = str(item.get("materialId") or item.get("id") or "").strip()
    if not material_id:
        return item
    cache_dir = work_dir / "target"
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    source_kind = "raw"
    try:
        payload, source_kind = run_awaitable_sync(downloadable_business_fill_source_payload(material_id))
    except Exception:
        payload = {}
    if not payload:
        return item
    file_name = safe_filename(
        str(payload.get("fileName") or item.get("fileName") or item.get("materialName") or f"{material_id}.docx"),
        f"{material_id}.docx",
    )
    target_path = cache_dir / f"{material_id}-{file_name}"
    if not target_path.exists():
        minio_client.download_file(str(payload["bucket"]), str(payload["key"]), target_path)
    item.update(
        {
            "filePath": str(target_path),
            "path": str(target_path),
            "fileName": target_path.name,
            "sourceKind": str(item.get("sourceKind") or source_kind),
            "mimeType": str(payload.get("mimeType") or item.get("mimeType") or mimetypes.guess_type(target_path.name)[0] or "application/octet-stream"),
        }
    )
    return item


def prepare_business_table_fill_sources(source_materials: list[dict[str, Any]], work_dir: Path) -> list[dict[str, Any]]:
    cache_dir = work_dir / "source-materials"
    cache_dir.mkdir(parents=True, exist_ok=True)
    prepared: list[dict[str, Any]] = []
    for index, material in enumerate(source_materials, start=1):
        item = copy.deepcopy(material)
        material_id = str(item.get("id") or item.get("materialId") or "").strip()
        if not material_id:
            continue
        try:
            payload, source_kind = run_awaitable_sync(downloadable_business_fill_source_payload(material_id))
            file_name = safe_filename(
                str(payload.get("fileName") or item.get("materialName") or item.get("name") or f"{material_id}.bin"),
                f"{material_id}.bin",
            )
            target_path = cache_dir / f"{index:02d}-{material_id}-{file_name}"
            if not target_path.exists():
                minio_client.download_file(str(payload["bucket"]), str(payload["key"]), target_path)
            item.update(
                {
                    "path": str(target_path),
                    "fileName": target_path.name,
                    "sourceKind": source_kind,
                    "mimeType": str(payload.get("mimeType") or ""),
                }
            )
        except Exception as exc:
            item["prepareError"] = str(exc)
        prepared.append(item)
    return prepared


async def downloadable_business_fill_source_payload(material_id: str) -> tuple[dict[str, Any], str]:
    try:
        payload = await business_material_store.raw_download_cleaned_content(material_id)
        return payload, "cleaned"
    except Exception:
        payload = await business_material_store.raw_download_content(material_id)
    mime_type = str(payload.get("mimeType") or "")
    file_name = str(payload.get("fileName") or "").lower()
    allowed_ext = file_name.endswith((".docx", ".xlsx", ".xlsm"))
    allowed_mime = (
        "wordprocessingml" in mime_type
        or "spreadsheetml" in mime_type
        or "ms-excel" in mime_type
    )
    if not allowed_ext and not allowed_mime:
        raise ValueError(f"素材 {material_id} 不是填写 Skill 可读取的 Word/Excel。")
    return payload, "raw"
