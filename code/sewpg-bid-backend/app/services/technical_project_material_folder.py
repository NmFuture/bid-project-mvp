from __future__ import annotations

import re
from typing import Any

from app.services.peripheral import PeripheralError
from app.services.technical_material_store import technical_material_store


TECHNICAL_PROJECT_ROOT = "技术标/项目定制"
TECHNICAL_APPENDIX_FOLDER_NAME = "附表"
_ILLEGAL_FOLDER_CHARS = re.compile(r'[\\/:*?"<>|]')


def _project_folder_name(project: dict[str, Any]) -> str:
    name = str(project.get("name") or "").strip()
    if not name:
        raise PeripheralError(400, "请先完善项目名称。", "PROJECT_NAME_REQUIRED")
    if _ILLEGAL_FOLDER_CHARS.search(name):
        raise PeripheralError(
            400,
            '项目名称不能包含 \\ / : * ? " < > | 字符。',
            "PROJECT_NAME_INVALID",
        )
    return name


def _walk_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    stack = list(nodes)
    while stack:
        node = stack.pop()
        result.append(node)
        stack.extend(item for item in node.get("children") or [] if isinstance(item, dict))
    return result


async def resolve_technical_project_folder_path(project_id: str) -> str:
    """按项目 id 找它在「技术标/项目定制」下的目录路径，找不到返回空串。

    走 identity_options 而不是 raw_tree：技术标目录树节点不带 projectId，
    只有 identity_options 会把目录归属的项目 id 和路径对上。
    """

    target_id = str(project_id or "").strip()
    if not target_id:
        return ""
    payload = await technical_material_store.identity_options()
    for item in payload.get("projects") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("projectId") or item.get("id") or "") != target_id:
            continue
        path = str(item.get("folderPath") or "")
        return path if path.startswith(f"{TECHNICAL_PROJECT_ROOT}/") else ""
    return ""


async def prepare_technical_project_material_folder(
    project: dict[str, Any],
    *,
    appendix_material_ids: list[str] | None = None,
) -> dict[str, Any]:
    """按项目名称准备项目目录，并保留稳定项目 ID 作为目录归属标识。"""

    project_name = _project_folder_name(project)
    # 目录归属恒为项目自身 id：素材来源项目只是复制模板，不能改写本项目的素材身份，
    # 否则下面的 owned_node 会认到来源项目的目录并把它改名（目录劫持）。
    material_project_id = str(project.get("id") or "").strip()
    if not material_project_id:
        raise PeripheralError(400, "项目素材 ID 为空。", "PROJECT_ID_REQUIRED")

    target_path = f"{TECHNICAL_PROJECT_ROOT}/{project_name}"
    tree_payload = await technical_material_store.raw_tree()
    nodes = _walk_tree([item for item in tree_payload.get("tree") or [] if isinstance(item, dict)])
    project_nodes = [
        item
        for item in nodes
        if str(item.get("path") or "").startswith(f"{TECHNICAL_PROJECT_ROOT}/")
        and len(str(item.get("path") or "").strip("/").split("/")) == 3
    ]
    target_node = next((item for item in project_nodes if str(item.get("path") or "") == target_path), None)
    owned_node = next(
        (item for item in project_nodes if str(item.get("projectId") or "") == material_project_id),
        None,
    )

    if target_node is not None:
        target_owner = await technical_material_store.raw_project_folder_owner(target_path)
        if target_owner != material_project_id:
            raise PeripheralError(
                409,
                "已存在相同项目，请修改项目名称。",
                "PROJECT_NAME_DUPLICATE",
            )

    if owned_node is not None and str(owned_node.get("path") or "") != target_path:
        if target_node is not None:
            raise PeripheralError(409, "项目名称对应的素材目录已存在。", "RAW_FOLDER_EXISTS")
        await technical_material_store.raw_migrate_project_folder(
            path=str(owned_node.get("path") or ""),
            new_name=project_name,
        )
    elif target_node is None:
        bootstrap_result = await technical_material_store.raw_bootstrap_folders(material_project_id)
        old_path = str((bootstrap_result.get("payload") or {}).get("path") or "").strip()
        if old_path != target_path:
            await technical_material_store.raw_migrate_project_folder(path=old_path, new_name=project_name)

    appendix_path = f"{target_path}/{TECHNICAL_APPENDIX_FOLDER_NAME}"
    refreshed_tree = await technical_material_store.raw_tree()
    refreshed_nodes = _walk_tree(
        [item for item in refreshed_tree.get("tree") or [] if isinstance(item, dict)]
    )
    if not any(str(item.get("path") or "") == appendix_path for item in refreshed_nodes):
        try:
            await technical_material_store.raw_create_folder(target_path, TECHNICAL_APPENDIX_FOLDER_NAME)
        except PeripheralError as exc:
            if exc.code != "RAW_FOLDER_EXISTS":
                raise

    move_result = await technical_material_store.raw_batch_move_files(
        file_ids=appendix_material_ids or [],
        target_path=appendix_path,
        on_conflict="overwrite",
    )
    failed_moves = [item for item in move_result.get("failed") or [] if isinstance(item, dict)]
    if failed_moves:
        raise PeripheralError(
            500,
            f"附表目录迁移失败，共 {len(failed_moves)} 个文件未迁移。",
            "TECHNICAL_APPENDIX_FOLDER_MIGRATION_FAILED",
            {"failed": failed_moves},
        )

    return {
        "status": "ok",
        "projectId": material_project_id,
        "path": target_path,
        "appendixPath": appendix_path,
        "movedAppendixCount": len(move_result.get("succeeded") or []),
    }
