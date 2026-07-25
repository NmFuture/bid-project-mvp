from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


def _tree(*nodes: dict) -> dict:
    return {
        "tree": [
            {
                "path": "技术标",
                "children": [
                    {
                        "path": "技术标/项目定制",
                        "children": list(nodes),
                    }
                ],
            }
        ]
    }


def test_prepare_migrates_legacy_project_id_folder_and_creates_appendix_folder() -> None:
    from app.services.technical_project_material_folder import prepare_technical_project_material_folder

    project = {
        "id": "PRJ-0007",
        "bidType": "技术标",
        "name": "海上风电项目",
    }
    old_node = {
        "path": "技术标/项目定制/PRJ-0007",
        "projectId": "PRJ-0007",
        "children": [],
    }
    migrated_node = {
        "path": "技术标/项目定制/海上风电项目",
        "projectId": "PRJ-0007",
        "children": [],
    }

    with patch(
        "app.services.technical_project_material_folder.technical_material_store.raw_tree",
        new=AsyncMock(side_effect=[_tree(old_node), _tree(migrated_node)]),
    ), patch(
        "app.services.technical_project_material_folder.technical_material_store.raw_migrate_project_folder",
        new=AsyncMock(return_value={}),
    ) as migrate, patch(
        "app.services.technical_project_material_folder.technical_material_store.raw_create_folder",
        new=AsyncMock(return_value={}),
    ) as create_folder, patch(
        "app.services.technical_project_material_folder.technical_material_store.raw_bootstrap_folders",
        new=AsyncMock(return_value={}),
    ) as bootstrap, patch(
        "app.services.technical_project_material_folder.technical_material_store.raw_batch_move_files",
        new=AsyncMock(return_value={"succeeded": ["RAW-0001"], "failed": []}),
    ) as move_files:
        result = asyncio.run(
            prepare_technical_project_material_folder(
                project,
                appendix_material_ids=["RAW-0001"],
            )
        )

    migrate.assert_awaited_once_with(path="技术标/项目定制/PRJ-0007", new_name="海上风电项目")
    bootstrap.assert_not_awaited()
    create_folder.assert_awaited_once_with("技术标/项目定制/海上风电项目", "附表")
    move_files.assert_awaited_once_with(
        file_ids=["RAW-0001"],
        target_path="技术标/项目定制/海上风电项目/附表",
        on_conflict="overwrite",
    )
    assert result["appendixPath"] == "技术标/项目定制/海上风电项目/附表"
    assert result["movedAppendixCount"] == 1


def test_prepare_is_idempotent_when_named_folder_and_appendix_exist() -> None:
    from app.services.technical_project_material_folder import prepare_technical_project_material_folder

    appendix_node = {"path": "技术标/项目定制/海上风电项目/附表", "children": []}
    project_node = {
        "path": "技术标/项目定制/海上风电项目",
        "projectId": "PRJ-0007",
        "children": [appendix_node],
    }
    raw_tree = AsyncMock(side_effect=[_tree(project_node), _tree(project_node)])
    with patch(
        "app.services.technical_project_material_folder.technical_material_store.raw_tree",
        new=raw_tree,
    ), patch(
        "app.services.technical_project_material_folder.technical_material_store.raw_migrate_project_folder",
        new=AsyncMock(),
    ) as migrate, patch(
        "app.services.technical_project_material_folder.technical_material_store.raw_create_folder",
        new=AsyncMock(),
    ) as create_folder, patch(
        "app.services.technical_project_material_folder.technical_material_store.raw_bootstrap_folders",
        new=AsyncMock(),
    ) as bootstrap, patch(
        "app.services.technical_project_material_folder.technical_material_store.raw_batch_move_files",
        new=AsyncMock(return_value={"succeeded": [], "failed": []}),
    ):
        asyncio.run(
            prepare_technical_project_material_folder(
                {"id": "PRJ-0007", "bidType": "技术标", "name": "海上风电项目"}
            )
        )

    migrate.assert_not_awaited()
    create_folder.assert_not_awaited()
    bootstrap.assert_not_awaited()


def test_prepare_rejects_named_folder_owned_by_another_project() -> None:
    from app.services.peripheral import PeripheralError
    from app.services.technical_project_material_folder import prepare_technical_project_material_folder

    foreign_node = {
        "path": "技术标/项目定制/海上风电项目",
        "projectId": "PRJ-0008",
        "children": [],
    }
    with patch(
        "app.services.technical_project_material_folder.technical_material_store.raw_tree",
        new=AsyncMock(return_value=_tree(foreign_node)),
    ), pytest.raises(PeripheralError) as exc_info:
        asyncio.run(
            prepare_technical_project_material_folder(
                {"id": "PRJ-0007", "bidType": "技术标", "name": "海上风电项目"}
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "已存在相同项目，请修改项目名称。"


def test_confirmation_rejects_duplicate_technical_project_name_before_side_effects() -> None:
    from fastapi import HTTPException

    from app.services.bid_project_service import BidProjectService

    service = BidProjectService(
        bid_type="技术标",
        not_found_message="技术标项目不存在。",
        wrong_type_message="该接口仅支持技术标项目。",
        delete_message="技术标项目已删除",
        bootstrap_material_folder=AsyncMock(),
    )
    current = {"id": "PRJ-0007", "bidType": "技术标", "name": "待修改项目"}
    with patch.object(service, "ensure_project", return_value=current), patch(
        "app.services.bid_project_service.list_workspace_projects",
        return_value={
            "items": [
                current,
                {"id": "PRJ-0008", "bidType": "技术标", "name": "海上风电项目"},
            ]
        },
    ), patch(
        "app.services.bid_project_service.prepare_technical_project_material_folder",
        new=AsyncMock(),
    ) as prepare_folder, patch(
        "app.services.bid_project_service.update_workspace_project",
    ) as update_project:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                service.update(
                    "PRJ-0007",
                    {"name": "海上风电项目", "reviewDecision": "participate"},
                )
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "已存在相同项目，请修改项目名称。"
    prepare_folder.assert_not_awaited()
    update_project.assert_not_called()
