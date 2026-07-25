from __future__ import annotations

import re
from typing import Any

from app.services.identity import build_project_material_scope
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


async def prepare_technical_project_material_folder(project: dict[str, Any]) -> dict[str, Any]:
    """按项目名称准备项目目录，并保留稳定项目 ID 作为目录归属标识。"""

    project_name = _project_folder_name(project)
    scope = build_project_material_scope(project)
    material_project_id = str((scope.get("identity") or {}).get("projectId") or "").strip()
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

    if target_node is not None and str(target_node.get("projectId") or "") != material_project_id:
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

    return {
        "status": "ok",
        "projectId": material_project_id,
        "path": target_path,
        "appendixPath": appendix_path,
    }
