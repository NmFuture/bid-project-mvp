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


def test_prepare_keeps_folder_owned_by_project_itself_when_source_selected() -> None:
    """选了素材来源项目也不能改写目录归属，否则会把来源项目的目录改名。"""

    from app.services.technical_project_material_folder import prepare_technical_project_material_folder

    project = {
        "id": "PRJ-0007",
        "bidType": "技术标",
        "name": "海上风电项目",
        "materialProjectId": "PRJ-0001",
        "materialSourceProjectId": "PRJ-0001",
    }
    source_node = {"path": "技术标/项目定制/华能0808", "projectId": "PRJ-0001", "children": []}
    created_node = {"path": "技术标/项目定制/海上风电项目", "projectId": "PRJ-0007", "children": []}

    with patch(
        "app.services.technical_project_material_folder.technical_material_store.raw_tree",
        new=AsyncMock(side_effect=[_tree(source_node), _tree(source_node, created_node)]),
    ), patch(
        "app.services.technical_project_material_folder.technical_material_store.raw_migrate_project_folder",
        new=AsyncMock(return_value={}),
    ) as migrate, patch(
        "app.services.technical_project_material_folder.technical_material_store.raw_bootstrap_folders",
        new=AsyncMock(return_value={"payload": {"path": "技术标/项目定制/海上风电项目"}}),
    ) as bootstrap, patch(
        "app.services.technical_project_material_folder.technical_material_store.raw_create_folder",
        new=AsyncMock(return_value={}),
    ), patch(
        "app.services.technical_project_material_folder.technical_material_store.raw_batch_move_files",
        new=AsyncMock(return_value={"succeeded": [], "failed": []}),
    ):
        result = asyncio.run(prepare_technical_project_material_folder(project))

    bootstrap.assert_awaited_once_with("PRJ-0007")
    migrate.assert_not_awaited()
    assert result["projectId"] == "PRJ-0007"
    assert result["path"] == "技术标/项目定制/海上风电项目"


def test_resolve_source_folder_path_reads_identity_options() -> None:
    """目录树节点不带 projectId，只有 identity_options 能把项目 id 和目录路径对上。"""

    from app.services.technical_project_material_folder import resolve_technical_project_folder_path

    options = {
        "projects": [
            {"id": "PRJ-0001", "projectId": "PRJ-0001", "folderPath": "技术标/项目定制/华能0808"},
            {"id": "PRJ-0002", "projectId": "PRJ-0002", "folderPath": ""},
        ]
    }
    with patch(
        "app.services.technical_project_material_folder.technical_material_store.identity_options",
        new=AsyncMock(return_value=options),
    ):
        assert asyncio.run(resolve_technical_project_folder_path("PRJ-0001")) == "技术标/项目定制/华能0808"
        assert asyncio.run(resolve_technical_project_folder_path("PRJ-0002")) == ""
        assert asyncio.run(resolve_technical_project_folder_path("PRJ-9999")) == ""


def test_update_schedules_copy_once_and_skips_when_source_already_recorded() -> None:
    from app.services.bid_project_service import BidProjectService

    service = BidProjectService(
        bid_type="技术标",
        not_found_message="技术标项目不存在。",
        wrong_type_message="该接口仅支持技术标项目。",
        delete_message="技术标项目已删除",
        bootstrap_material_folder=AsyncMock(),
    )
    current = {"id": "PRJ-0007", "bidType": "技术标", "name": "海上风电项目"}

    def run_update(project_state: dict, payload: dict) -> AsyncMock:
        with patch.object(service, "ensure_project", return_value=project_state), patch(
            "app.services.bid_project_service.list_workspace_projects",
            return_value={"items": [project_state]},
        ), patch(
            "app.services.bid_project_service.prepare_technical_project_material_folder",
            new=AsyncMock(return_value={"status": "ok", "path": "技术标/项目定制/海上风电项目"}),
        ), patch(
            "app.services.bid_project_service.resolve_technical_project_folder_path",
            new=AsyncMock(return_value="技术标/项目定制/华能0808"),
        ), patch(
            "app.services.bid_project_service.update_workspace_project",
            return_value=dict(project_state),
        ), patch(
            "app.services.bid_project_service.schedule_technical_material_copy",
            return_value={"status": "running"},
        ) as schedule:
            asyncio.run(service.update("PRJ-0007", payload))
        return schedule

    schedule = run_update(
        dict(current),
        {"reviewDecision": "participate", "materialSourceProjectId": "PRJ-0001"},
    )
    schedule.assert_called_once_with(
        "PRJ-0007",
        source_path="技术标/项目定制/华能0808",
        target_path="技术标/项目定制/海上风电项目",
        source_project_id="PRJ-0001",
    )

    # 已记过来源：再次保存不重复复制
    already = {**current, "reviewDecision": "participate", "materialSourceProjectId": "PRJ-0001"}
    schedule_again = run_update(already, {"name": "海上风电项目", "materialSourceProjectId": "PRJ-0001"})
    schedule_again.assert_not_called()


def test_update_rejects_missing_source_folder() -> None:
    from fastapi import HTTPException

    from app.services.bid_project_service import BidProjectService

    service = BidProjectService(
        bid_type="技术标",
        not_found_message="技术标项目不存在。",
        wrong_type_message="该接口仅支持技术标项目。",
        delete_message="技术标项目已删除",
        bootstrap_material_folder=AsyncMock(),
    )
    current = {"id": "PRJ-0007", "bidType": "技术标", "name": "海上风电项目"}

    with patch.object(service, "ensure_project", return_value=current), patch(
        "app.services.bid_project_service.list_workspace_projects",
        return_value={"items": [current]},
    ), patch(
        "app.services.bid_project_service.prepare_technical_project_material_folder",
        new=AsyncMock(return_value={"status": "ok", "path": "技术标/项目定制/海上风电项目"}),
    ), patch(
        "app.services.bid_project_service.resolve_technical_project_folder_path",
        new=AsyncMock(return_value=""),
    ), patch(
        "app.services.bid_project_service.update_workspace_project",
        return_value=dict(current),
    ), patch(
        "app.services.bid_project_service.schedule_technical_material_copy",
    ) as schedule:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                service.update(
                    "PRJ-0007",
                    {"reviewDecision": "participate", "materialSourceProjectId": "PRJ-9999"},
                )
            )

    assert exc_info.value.status_code == 404
    schedule.assert_not_called()
