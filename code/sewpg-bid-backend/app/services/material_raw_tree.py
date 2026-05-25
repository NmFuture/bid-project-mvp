from __future__ import annotations

from typing import Any

from app.services.material_folder_scope import MATERIAL_BID_TYPES


def build_raw_tree_payload(
    *,
    root_folders: list[Any],
    all_folders: list[Any],
    all_files: list[Any],
    bid_type: str,
    updated_at: str,
) -> dict[str, Any]:
    files_by_folder: dict[int, list[Any]] = {}
    for item in all_files:
        files_by_folder.setdefault(int(getattr(item, "folder_id")), []).append(item)

    children_by_parent: dict[int, list[Any]] = {}
    for folder in all_folders:
        parent_id = getattr(folder, "parent_id", None)
        if parent_id is not None:
            children_by_parent.setdefault(int(parent_id), []).append(folder)

    def subtree_file_count(folder: Any) -> int:
        folder_id = int(getattr(folder, "id"))
        child_folders = children_by_parent.get(folder_id, [])
        return len(files_by_folder.get(folder_id, [])) + sum(subtree_file_count(child) for child in child_folders)

    def build_node(folder: Any) -> dict[str, Any]:
        folder_id = int(getattr(folder, "id"))
        child_folders = children_by_parent.get(folder_id, [])
        direct_file_count = len(files_by_folder.get(folder_id, []))
        return {
            "id": getattr(folder, "path"),
            "name": getattr(folder, "name"),
            "path": getattr(folder, "path"),
            "directFileCount": direct_file_count,
            "fileCount": subtree_file_count(folder),
            "children": [build_node(child) for child in child_folders],
        }

    folders_by_path = {str(getattr(folder, "path", "") or ""): folder for folder in all_folders}
    roots = [folders_by_path.get(str(getattr(root, "path", "") or "")) or root for root in root_folders]
    normalized_bid_type = str(bid_type or "").strip()
    if normalized_bid_type in MATERIAL_BID_TYPES:
        roots = [
            root
            for root in roots
            if str(getattr(root, "path", "") or getattr(root, "name", "") or "").split("/", 1)[0] == normalized_bid_type
        ]
    return {"tree": [build_node(root) for root in roots], "updatedAt": updated_at}
