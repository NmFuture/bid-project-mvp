from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.file_utils import safe_segment
from app.services.identity import build_project_identity
from app.services.material_folder_scope import project_material_root_path
from app.services.onlyoffice_documents import WORD_MEDIA_TYPE
from app.services.technical_material_index import rebuild_technical_material_index_strict
from app.services.technical_material_store import technical_material_store


class TechnicalParseAssetError(RuntimeError):
    pass


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
    """把技术标解析出的附表同步到当前项目素材根目录并刷新全局索引。"""

    if str(project.get("bidType") or "") != TECHNICAL_BID_TYPE:
        raise TechnicalParseAssetError("仅技术标解析附表支持该同步操作。")

    structured = parse_result.get("structured") if isinstance(parse_result.get("structured"), dict) else {}
    appendices = structured.get("appendices") if isinstance(structured.get("appendices"), list) else []
    files = [_appendix_material_file(item) for item in appendices if isinstance(item, dict)]
    if not files:
        return {"status": "skipped", "syncedCount": 0, "items": []}

    identity = build_project_identity(project)
    material_project_id = str(identity.get("projectId") or "").strip()
    if not material_project_id:
        raise TechnicalParseAssetError("项目素材 ID 为空，无法同步技术标附表。")

    await technical_material_store.raw_bootstrap_folders(material_project_id)
    result = await technical_material_store.raw_upload(
        target_path=project_material_root_path(TECHNICAL_BID_TYPE, material_project_id),
        project_id=material_project_id,
        project_code=str(identity.get("projectCode") or material_project_id),
        project_name=str(identity.get("projectName") or project.get("name") or ""),
        material_tier="project",
        customer_id=str(identity.get("customerId") or ""),
        customer_name=str(identity.get("customerCanonicalName") or identity.get("customerName") or ""),
        on_conflict="version",
        files=files,
    )
    uploaded_items = [item for item in result.get("items") or [] if isinstance(item, dict)]
    if len(uploaded_items) != len(files):
        raise TechnicalParseAssetError("技术标附表未全部写入项目素材库。")

    index_payload = await rebuild_technical_material_index_strict()
    missing_ids = {
        str(item.get("id") or "")
        for item in uploaded_items
        if str(item.get("id") or "") not in _indexed_file_ids(index_payload)
    }
    if missing_ids:
        raise TechnicalParseAssetError("技术标附表已入库，但全局素材目录 JSON 未包含新增文件。")

    return {
        "status": "synced",
        "syncedCount": len(uploaded_items),
        "items": uploaded_items,
        "targetPath": project_material_root_path(TECHNICAL_BID_TYPE, material_project_id),
    }
