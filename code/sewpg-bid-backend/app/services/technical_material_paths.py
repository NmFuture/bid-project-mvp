from __future__ import annotations

from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.peripheral import PeripheralError

TECHNICAL_STANDARD_FOLDER_NAME = "标准文件"
TECHNICAL_ALLOWED_WRITE_ROOTS = {
    TECHNICAL_STANDARD_FOLDER_NAME,
    "客户定制",
    "项目定制",
}
TECHNICAL_LEGACY_WRITE_ROOT_ALIASES = {
    "客户素材": "客户定制",
    "项目素材": "项目定制",
}


def normalize_technical_material_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/")


def ensure_technical_material_path(path: str, label: str = "路径") -> str:
    normalized = normalize_technical_material_path(path)
    if normalized and normalized != TECHNICAL_BID_TYPE and not normalized.startswith(f"{TECHNICAL_BID_TYPE}/"):
        raise PeripheralError(400, f"{label}必须位于技术标素材库。", "TECHNICAL_MATERIAL_PATH_REQUIRED")
    return normalized


def ensure_technical_material_write_path(path: str, label: str = "目标目录", *, allow_root: bool = False) -> str:
    normalized = ensure_technical_material_path(path, label)
    if allow_root and normalized == TECHNICAL_BID_TYPE:
        return normalized
    parts = [part for part in normalized.split("/") if part]
    if len(parts) >= 2 and parts[1] in TECHNICAL_LEGACY_WRITE_ROOT_ALIASES:
        parts[1] = TECHNICAL_LEGACY_WRITE_ROOT_ALIASES[parts[1]]
        normalized = "/".join(parts)
    if len(parts) < 2 or parts[0] != TECHNICAL_BID_TYPE or parts[1] not in TECHNICAL_ALLOWED_WRITE_ROOTS:
        allowed = "、".join(f"{TECHNICAL_BID_TYPE}/{name}" for name in sorted(TECHNICAL_ALLOWED_WRITE_ROOTS))
        raise PeripheralError(
            400,
            f"{label}只能位于 {allowed} 之一。",
            "TECHNICAL_MATERIAL_WRITE_PATH_REQUIRED",
        )
    return normalized


def ensure_technical_material_new_child_path(parent_path: str, folder_name: str, label: str = "父级目录") -> str:
    normalized_parent = ensure_technical_material_path(parent_path, label)
    clean_name = normalize_technical_material_path(folder_name)
    clean_name = TECHNICAL_LEGACY_WRITE_ROOT_ALIASES.get(clean_name, clean_name)
    if normalized_parent == TECHNICAL_BID_TYPE and clean_name not in TECHNICAL_ALLOWED_WRITE_ROOTS:
        allowed = "、".join(sorted(TECHNICAL_ALLOWED_WRITE_ROOTS))
        raise PeripheralError(
            400,
            f"技术标根目录下只能创建 {allowed}。",
            "TECHNICAL_MATERIAL_ROOT_CHILD_REQUIRED",
        )
    if normalized_parent != TECHNICAL_BID_TYPE:
        normalized_parent = ensure_technical_material_write_path(normalized_parent, label)
    return normalized_parent


def canonical_technical_material_child_name(parent_path: str, folder_name: str) -> str:
    normalized_parent = ensure_technical_material_path(parent_path, "父级目录")
    clean_name = normalize_technical_material_path(folder_name)
    if normalized_parent == TECHNICAL_BID_TYPE:
        return TECHNICAL_LEGACY_WRITE_ROOT_ALIASES.get(clean_name, clean_name)
    return folder_name
