from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from app.core.config import settings
from app.services.bid_runtime_state import read_json_file, write_json_file_atomic
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.material_tags import normalize_material_tags
from app.services.material_taxonomy import normalize_material_tier

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

# 标签真值归属：自 v2 起，技术标 tag 的真值在本 JSON 索引自身，
# 而非 DB raw_files.ext_fields.tags（后者退役为非真值，仅在首次迁移时作种子）。
TAGS_SOURCE_OF_TRUTH = "index"

# 后端数据目录下的索引文件（非素材库、非数据库）。
TECHNICAL_MATERIAL_INDEX_PATH = (
    settings.documents_dir / "_runtime" / "materials" / "technical_material_index.json"
)

# 写盘串行化：rebuild（结构变更钩子触发）与 set_tags_for_node（人工打 tag）
# 都改写同一份 JSON。JSON 当真值后，写丢就是真丢，故全程持锁 + 原子写。
_INDEX_WRITE_LOCK = asyncio.Lock()

# --------------------------------------------------------------------------- #
# 旧索引 -> tag 认领表
# --------------------------------------------------------------------------- #


def _resolve_tier(folder_name: str) -> str:
    """按 2 级目录名判定 tier（standard/customer/project）。"""
    tier = normalize_material_tier(folder_name)
    return tier or "standard"


def _canonical_tier(folder_name: str) -> str:
    """只识别明确的档位根目录；未知二级目录不再被当作独立档位。"""
    name = str(folder_name or "").strip()
    if name == "标准文件":
        return "standard"
    return normalize_material_tier(name)


def _now_display() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _material_folder_key(folder_path: str) -> str:
    """把文件路径归并到索引目录节点。

    规范档位下保持“第 3 级目录”为节点；未知二级目录不进入 Wiki 索引。
    """
    parts = [part for part in _normalize_path(folder_path).split("/") if part]
    if len(parts) < 2 or parts[0] != TECHNICAL_BID_TYPE:
        return ""
    if not _canonical_tier(parts[1]) or len(parts) < 3:
        return ""
    return "/".join(parts[:3])


def _third_level_path(folder_path: str) -> str:
    """把任意 folderPath 归并到它所属的索引目录节点。"""
    return _material_folder_key(folder_path)


def _coerce_folder_id(value: Any) -> str:
    """把 tree 节点的 folderId 归一为字符串键（认领表用）。空/缺失 -> ""。"""
    if value is None:
        return ""
    return str(value).strip()


def _collect_prior_tags(prev: dict[str, Any]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """从旧 JSON 索引提取 tag 真值，建认领表。

    返回 (files_by_id, folders_by_id)：
    - files_by_id:   {RAW-xxxx -> tags}
    - folders_by_id: {folderId(str) -> tags}（tier 与 3 级 folder 共用此表）

    认领键用 id（文件 RAW-xxxx / 目录 folderId），不用 path —— 改名/移动 tag 不丢。
    """
    files_by_id: dict[str, list[str]] = {}
    folders_by_id: dict[str, list[str]] = {}

    for tier in prev.get("tiers") or []:
        tier_fid = _coerce_folder_id(tier.get("folderId"))
        if tier_fid:
            folders_by_id[tier_fid] = list(tier.get("tags") or [])
        for folder in tier.get("folders") or []:
            fid = _coerce_folder_id(folder.get("folderId"))
            if fid:
                folders_by_id[fid] = list(folder.get("tags") or [])
            for file_item in folder.get("files") or []:
                file_id = str(file_item.get("id") or "")
                if file_id:
                    files_by_id[file_id] = list(file_item.get("tags") or [])

    return files_by_id, folders_by_id


def _is_seedable(prev: dict[str, Any]) -> bool:
    """旧索引是否仍需从 DB 种 tag（首次迁移）。

    旧索引缺失、或 schemaVersion < 2 时，视为尚未迁移：file tag 用 DB ext.tags 作种子。
    一旦升到 v2，DB 不再是 file tag 真值，只认旧 JSON。
    """
    if not prev:
        return True
    try:
        return int(prev.get("schemaVersion") or 0) < SCHEMA_VERSION
    except (TypeError, ValueError):
        return True


# --------------------------------------------------------------------------- #
# 节点构建
# --------------------------------------------------------------------------- #


def _file_entry(
    item: dict[str, Any],
    *,
    files_by_id: dict[str, list[str]],
    seed_from_db: bool,
) -> dict[str, Any]:
    folder_path = _normalize_path(item.get("folderPath"))
    name = str(item.get("name") or "")
    full_path = f"{folder_path}/{name}" if folder_path else name
    file_id = str(item.get("id") or "")

    # tag 真值优先取旧 JSON（按 id 认领）；旧索引未迁移时从 DB ext.tags 种子。
    if file_id in files_by_id:
        tags = files_by_id[file_id]
    elif seed_from_db:
        tags = normalize_material_tags(item.get("tags"))
    else:
        tags = []

    entry = {
        "id": file_id,
        "name": name,
        "path": full_path,
        "ext": str(item.get("ext") or item.get("type") or ""),
        "tags": tags,
    }

    return entry


def _build_payload(
    tree: dict[str, Any],
    file_items: list[dict[str, Any]],
    *,
    prev: dict[str, Any] | None = None,
) -> dict[str, Any]:
    generated_at = _now_display()
    prior = prev or {}
    files_by_id, folders_by_id = _collect_prior_tags(prior)
    seed_from_db = _is_seedable(prior)

    # 把文件按所属目录节点归并。
    files_by_third: dict[str, list[dict[str, Any]]] = {}
    for item in file_items:
        third = _material_folder_key(item.get("folderPath"))
        if not third:
            continue
        entry = _file_entry(
            item,
            files_by_id=files_by_id,
            seed_from_db=seed_from_db,
        )
        files_by_third.setdefault(third, []).append(entry)

    # 技术标 root（1 级）的直接子节点 = 2 级 tier 目录。
    root_nodes = [
        node
        for node in (tree.get("tree") or [])
        if _normalize_path(node.get("path")) == TECHNICAL_BID_TYPE
    ]
    root_children = root_nodes[0].get("children") if root_nodes else []

    tiers: list[dict[str, Any]] = []
    total_files = 0
    total_third_folders = 0

    def build_folder(
        node: dict[str, Any],
        *,
        tier_value: str,
        generated_at: str,
    ) -> dict[str, Any]:
        folder_path = _normalize_path(node.get("path"))
        folder_fid = _coerce_folder_id(node.get("folderId"))
        files = files_by_third.get(folder_path, [])
        return {
            "name": str(node.get("name") or ""),
            "path": folder_path,
            "tier": tier_value,
            "folderId": folder_fid,
            "customerName": "",
            "customerId": "",
            "projectId": "",
            "projectCode": "",
            "description": "",
            "fileCount": len(files),
            "updatedAt": generated_at,
            # 目录 tag 真值在 JSON：按 folderId 从旧索引认领，新目录默认空。
            "tags": folders_by_id.get(folder_fid, []),
            "files": files,
        }

    for tier_node in root_children or []:
        tier_name = str(tier_node.get("name") or "")
        tier_value = _canonical_tier(tier_name)
        tier_path = _normalize_path(tier_node.get("path"))
        tier_fid = _coerce_folder_id(tier_node.get("folderId"))

        if not tier_value:
            continue

        folders: list[dict[str, Any]] = []
        tier_file_count = 0

        for third_node in tier_node.get("children") or []:
            folder = build_folder(third_node, tier_value=tier_value, generated_at=generated_at)
            tier_file_count += folder["fileCount"]
            total_third_folders += 1
            folders.append(folder)

        # 客户/项目档的 3 级目录名即客户名/项目标识，回填到对应字段。
        for folder in folders:
            if tier_value == "customer":
                folder["customerName"] = folder["name"]
            elif tier_value == "project":
                folder["projectId"] = folder["name"]

        total_files += tier_file_count
        tier = {
            "name": tier_name,
            "tier": tier_value,
            "path": tier_path,
            "folderId": tier_fid,
            "fileCount": tier_file_count,
            "tags": folders_by_id.get(tier_fid, []),
            "folders": folders,
        }
        tiers.append(tier)

    return {
        "bidType": TECHNICAL_BID_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "tagsSourceOfTruth": TAGS_SOURCE_OF_TRUTH,
        "generatedAt": generated_at,
        "stats": {
            "tierCount": len(tiers),
            "thirdLevelFolderCount": total_third_folders,
            "fileCount": total_files,
        },
        "tiers": tiers,
    }


def _write_index(payload: dict[str, Any]) -> None:
    write_json_file_atomic(TECHNICAL_MATERIAL_INDEX_PATH, payload)


async def _rebuild_payload(
    prev: dict[str, Any],
) -> dict[str, Any]:
    """从 DB 实时结构 + 旧索引 tag 重建 payload（不写盘）。"""
    # 延迟导入，避免与 technical_material_store 形成循环引用。
    from app.services.technical_material_store import technical_material_store

    tree = await technical_material_store.raw_tree()
    files = await technical_material_store.raw_files(
        folder_path=TECHNICAL_BID_TYPE,
        recursive=True,
        page=1,
        page_size=100000,
        use_index_tags=False,
    )
    file_items = list(files.get("items") or [])

    return _build_payload(tree, file_items, prev=prev)


async def rebuild_technical_material_index_strict() -> dict[str, Any]:
    """从数据库严格重建索引；失败时向调用方暴露异常。"""

    async with _INDEX_WRITE_LOCK:
        prev = load_technical_material_index()
        payload = await _rebuild_payload(prev)
        _write_index(payload)
        return payload


async def rebuild_technical_material_index() -> dict[str, Any]:
    """以 best-effort 方式重建索引，避免普通素材操作被索引异常阻断。"""

    try:
        return await rebuild_technical_material_index_strict()
    except Exception:  # noqa: BLE001 - 钩子是 best-effort，失败不阻断主流程
        logger.warning("technical material index rebuild failed", exc_info=True)
        return {}


def load_technical_material_index() -> dict[str, Any]:
    """读取已落盘的技术标三级目录 JSON 索引；不存在或损坏时返回 {}。"""
    return read_json_file(TECHNICAL_MATERIAL_INDEX_PATH)


# --------------------------------------------------------------------------- #
# 写 tag（人工就地标注，真值落 JSON）
# --------------------------------------------------------------------------- #


def _match_file(node_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    for tier in payload.get("tiers") or []:
        for folder in tier.get("folders") or []:
            for file_item in folder.get("files") or []:
                if str(file_item.get("id") or "") == node_id:
                    return file_item
    return None


def file_tags_by_id(payload: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """Return technical material file tags keyed by RAW id from the JSON index."""
    source = payload if payload is not None else load_technical_material_index()
    files_by_id, _ = _collect_prior_tags(source or {})
    return {file_id: normalize_material_tags(tags) for file_id, tags in files_by_id.items()}


def _match_folder(target_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """按 folderId 或 path 定位 tier / 3 级 folder 节点。"""
    target = _coerce_folder_id(target_id)
    target_path = _normalize_path(target_id)
    for tier in payload.get("tiers") or []:
        if (target and _coerce_folder_id(tier.get("folderId")) == target) or (
            target_path and _normalize_path(tier.get("path")) == target_path
        ):
            return tier
        for folder in tier.get("folders") or []:
            if (target and _coerce_folder_id(folder.get("folderId")) == target) or (
                target_path and _normalize_path(folder.get("path")) == target_path
            ):
                return folder
    return None


async def set_tags_for_node(*, target_id: str, tags: Any, merge: bool = False) -> dict[str, Any]:
    """对索引中某节点（文件 RAW-xxxx / 目录 folderId 或 path）设置 tag。

    tag 真值落 JSON：定位节点 -> normalize_material_tags 规整 -> 写回 -> 返回该节点。
    全程持写锁 + 原子写，与 rebuild 串行。

    merge=True 时在锁内重新读取节点当前 tags 并与传入 tags 取并集后写入，
    避免调用方用过期快照整条覆盖、丢失期间新增的标签（H4）。
    """
    target = str(target_id or "").strip()
    if not target:
        raise ValueError("targetId 不能为空")

    normalized = normalize_material_tags(tags)

    async with _INDEX_WRITE_LOCK:
        payload = load_technical_material_index()
        if not payload:
            payload = await _rebuild_payload({})

        if target.startswith("RAW-"):
            node = _match_file(target, payload)
        else:
            node = _match_folder(target, payload)

        if node is None:
            raise LookupError(f"未在索引中找到节点：{target}")

        if merge:
            # 锁内 read-merge-write：与当前真值取并集，吸收 preview 后新增的标签（H4）
            current = normalize_material_tags(node.get("tags"))
            node["tags"] = normalize_material_tags([*current, *normalized])
        else:
            node["tags"] = normalized
        _write_index(payload)
        return node
