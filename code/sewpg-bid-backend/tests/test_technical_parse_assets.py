from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


def test_sync_technical_parse_appendices_uploads_prefixed_files_and_refreshes_index(tmp_path: Path) -> None:
    from app.services.technical_parse_assets import sync_technical_parse_appendices

    appendix_path = tmp_path / "APPX-0001-附表A.1 投标机型总方案信息表.docx"
    appendix_path.write_bytes(b"docx-content")
    project = {
        "id": "PRJ-TECH-001",
        "bidType": "技术标",
        "name": "技术标附表入库测试",
        "projectCode": "TECH-2026-001",
        "materialProjectId": "MAT-TECH-001",
        "customerName": "测试业主",
    }
    parse_result = {
        "status": "completed",
        "structured": {
            "appendices": [
                {
                    "id": "APPX-0001",
                    "title": "附表A.1 投标机型总方案信息表",
                    "docxPath": str(appendix_path),
                    "selectedForMaterial": True,
                }
            ]
        },
    }
    upload_calls: list[dict[str, object]] = []

    async def fake_raw_upload(**kwargs):
        upload_calls.append(kwargs)
        return {
            "items": [
                {
                    "id": "RAW-TECH-001",
                    "name": "待填写-附表A.1 投标机型总方案信息表.docx",
                    "folderPath": "技术标/项目定制/MAT-TECH-001",
                }
            ]
        }

    rebuilt_index = {
        "tiers": [
            {
                "folders": [
                    {
                        "files": [
                            {
                                "id": "RAW-TECH-001",
                                "name": "待填写-附表A.1 投标机型总方案信息表.docx",
                            }
                        ]
                    }
                ]
            }
        ]
    }

    with patch(
        "app.services.technical_parse_assets.technical_material_store.raw_bootstrap_folders",
        new=AsyncMock(return_value={"payload": {"path": "技术标/项目定制/MAT-TECH-001"}}),
    ) as bootstrap_folders, patch(
        "app.services.technical_parse_assets.technical_material_store.raw_upload",
        side_effect=fake_raw_upload,
    ), patch(
        "app.services.technical_parse_assets.rebuild_technical_material_index_strict",
        new=AsyncMock(return_value=rebuilt_index),
    ) as rebuild_index:
        result = asyncio.run(sync_technical_parse_appendices(project, parse_result))

    assert result["status"] == "synced"
    assert result["syncedCount"] == 1
    bootstrap_folders.assert_awaited_once_with("MAT-TECH-001")
    assert len(upload_calls) == 1
    assert upload_calls[0]["target_path"] == "技术标/项目定制/MAT-TECH-001"
    assert upload_calls[0]["project_id"] == "MAT-TECH-001"
    assert upload_calls[0]["project_code"] == "TECH-2026-001"
    assert upload_calls[0]["material_tier"] == "project"
    assert upload_calls[0]["on_conflict"] == "overwrite"
    assert upload_calls[0]["files"] == [
        {
            "name": "待填写-附表A.1 投标机型总方案信息表.docx",
            "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "data": b"docx-content",
            "relativePath": "",
        }
    ]
    rebuild_index.assert_awaited_once_with()
    assert result["targetPath"] == "技术标/项目定制/MAT-TECH-001"


def test_sync_technical_parse_appendices_reconciles_to_latest_selection(tmp_path: Path) -> None:
    from app.services.technical_parse_assets import sync_technical_parse_appendices

    appendix_c_path = tmp_path / "appendix-c.docx"
    appendix_c_path.write_bytes(b"appendix-c")
    project = {
        "id": "PRJ-TECH-001",
        "bidType": "技术标",
        "name": "重选覆盖测试",
        "projectCode": "TECH-2026-001",
        "materialProjectId": "MAT-TECH-001",
    }
    parse_result = {
        "status": "completed",
        "structured": {
            "appendices": [
                {"id": "APPX-A", "title": "附表A", "selectedForMaterial": False},
                {"id": "APPX-B", "title": "附表B", "selectedForMaterial": True},
                {
                    "id": "APPX-C",
                    "title": "附表C",
                    "docxPath": str(appendix_c_path),
                    "selectedForMaterial": True,
                },
            ],
            "technicalAppendixMaterialSync": {
                "items": [
                    {"appendixId": "APPX-A", "materialId": "RAW-A", "name": "待填写-附表A.docx"},
                    {"appendixId": "APPX-B", "materialId": "RAW-B", "name": "待填写-附表B.docx"},
                ]
            },
        },
    }
    upload_calls: list[dict[str, object]] = []

    async def fake_raw_upload(**kwargs):
        upload_calls.append(kwargs)
        return {
            "items": [
                {
                    "id": "RAW-C",
                    "name": "待填写-附表C.docx",
                    "folderPath": "技术标/项目定制/MAT-TECH-001",
                }
            ]
        }

    initial_index = {
        "tiers": [
            {
                "folders": [
                    {
                        "files": [
                            {"id": "RAW-A", "name": "待填写-附表A.docx"},
                            {"id": "RAW-B", "name": "待填写-附表B.docx"},
                        ]
                    }
                ]
            }
        ]
    }
    rebuilt_index = {
        "tiers": [
            {
                "folders": [
                    {
                        "files": [
                            {"id": "RAW-B", "name": "待填写-附表B.docx"},
                            {"id": "RAW-C", "name": "待填写-附表C.docx"},
                        ]
                    }
                ]
            }
        ]
    }

    with patch(
        "app.services.technical_parse_assets.technical_material_store.raw_bootstrap_folders",
        new=AsyncMock(return_value={}),
    ), patch(
        "app.services.technical_parse_assets.technical_material_store.raw_upload",
        side_effect=fake_raw_upload,
    ), patch(
        "app.services.technical_parse_assets.technical_material_store.raw_batch_delete_files",
        new=AsyncMock(return_value={"succeeded": ["RAW-A"], "failed": []}),
    ) as delete_files, patch(
        "app.services.technical_parse_assets.rebuild_technical_material_index_strict",
        new=AsyncMock(side_effect=[initial_index, rebuilt_index]),
    ):
        result = asyncio.run(sync_technical_parse_appendices(project, parse_result))

    assert len(upload_calls) == 1
    assert [item["name"] for item in upload_calls[0]["files"]] == ["待填写-附表C.docx"]
    delete_files.assert_awaited_once_with(["RAW-A"])
    assert result["selectedCount"] == 2
    assert result["uploadedCount"] == 1
    assert result["deletedCount"] == 1
    assert parse_result["structured"]["technicalAppendixMaterialSync"]["items"] == [
        {"appendixId": "APPX-B", "materialId": "RAW-B", "name": "待填写-附表B.docx"},
        {"appendixId": "APPX-C", "materialId": "RAW-C", "name": "待填写-附表C.docx"},
    ]


def test_sync_technical_parse_appendices_recovers_missing_tracked_materials(tmp_path: Path) -> None:
    from app.services.technical_parse_assets import sync_technical_parse_appendices

    appendix_a_path = tmp_path / "appendix-a.docx"
    appendix_a_path.write_bytes(b"appendix-a")
    project = {
        "id": "PRJ-TECH-001",
        "bidType": "技术标",
        "name": "缺失素材恢复测试",
        "materialProjectId": "MAT-TECH-001",
    }
    parse_result = {
        "status": "completed",
        "structured": {
            "appendices": [
                {
                    "id": "APPX-A",
                    "title": "附表A",
                    "docxPath": str(appendix_a_path),
                    "selectedForMaterial": True,
                },
                {"id": "APPX-B", "title": "附表B", "selectedForMaterial": False},
            ],
            "technicalAppendixMaterialSync": {
                "items": [
                    {"appendixId": "APPX-A", "materialId": "RAW-A", "name": "待填写-附表A.docx"},
                    {"appendixId": "APPX-B", "materialId": "RAW-B", "name": "待填写-附表B.docx"},
                ],
                "pendingDeleteIds": ["RAW-B"],
            },
        },
    }

    with patch(
        "app.services.technical_parse_assets.technical_material_store.raw_bootstrap_folders",
        new=AsyncMock(return_value={}),
    ), patch(
        "app.services.technical_parse_assets.technical_material_store.raw_upload",
        new=AsyncMock(
            return_value={
                "items": [
                    {
                        "id": "RAW-A2",
                        "name": "待填写-附表A.docx",
                        "folderPath": "技术标/项目定制/MAT-TECH-001",
                    }
                ]
            }
        ),
    ) as upload, patch(
        "app.services.technical_parse_assets.technical_material_store.raw_batch_delete_files",
        new=AsyncMock(return_value={"succeeded": [], "failed": []}),
    ) as delete_files, patch(
        "app.services.technical_parse_assets.rebuild_technical_material_index_strict",
        new=AsyncMock(
            side_effect=[
                {"tiers": []},
                {"tiers": [{"folders": [{"files": [{"id": "RAW-A2"}]}]}]},
            ]
        ),
    ):
        result = asyncio.run(sync_technical_parse_appendices(project, parse_result))

    upload.assert_awaited_once()
    delete_files.assert_not_awaited()
    assert result["syncedCount"] == 1
    assert parse_result["structured"]["technicalAppendixMaterialSync"]["items"] == [
        {"appendixId": "APPX-A", "materialId": "RAW-A2", "name": "待填写-附表A.docx"}
    ]
    assert parse_result["structured"]["technicalAppendixMaterialSync"]["pendingDeleteIds"] == []


def test_set_technical_appendix_selection_persists_boolean_choice() -> None:
    from app.services.technical_parse_assets import set_technical_appendix_asset_selected

    project = {
        "id": "PRJ-TECH-001",
        "bidType": "技术标",
        "parse_result": {
            "status": "completed",
            "structured": {
                "appendices": [
                    {"id": "APPX-A", "title": "附表A", "selectedForMaterial": True},
                    {"id": "APPX-B", "title": "附表B", "selectedForMaterial": True},
                ]
            },
        },
        "parse_storage": {},
    }

    with patch(
        "app.services.technical_parse_assets.require_workspace_project_for_update",
        return_value=project,
    ), patch(
        "app.services.technical_parse_assets.persist_workspace_project_state",
    ) as persist_state:
        result = set_technical_appendix_asset_selected("PRJ-TECH-001", "APPX-A", selected=False)

    appendices = result["parseResult"]["structured"]["appendices"]
    assert [item["selectedForMaterial"] for item in appendices] == [False, True]
    assert result["selectedCount"] == 1
    persist_state.assert_called_once_with(project)


def test_technical_appendix_selection_only_saves_choice_and_returns_compact_payload() -> None:
    from app.services.bid_parse_service import TechnicalParseService

    parse_result = {
        "status": "completed",
        "structured": {
            "appendices": [{"id": "APPX-A", "selectedForMaterial": True}],
            "technicalAppendixMaterialSync": {
                "items": [{"appendixId": "APPX-A", "materialId": "RAW-A", "name": "附表A.docx"}]
            },
        },
    }
    project = {
        "id": "PRJ-TECH-001",
        "bidType": "技术标",
        "reviewDecision": "participate",
        "parse_result": parse_result,
    }

    class _TechnicalProjectService:
        bid_type = "技术标"

        @staticmethod
        def ensure_project(project_id: str) -> dict[str, object]:
            assert project_id == project["id"]
            return project

    service = TechnicalParseService(_TechnicalProjectService(), "/api/technical/projects")
    selection_result = {
        "message": "已更新附表素材选择。",
        "selectedCount": 1,
        "appendixCount": 1,
        "_participating": True,
        "parseResult": parse_result,
    }

    with patch(
        "app.services.bid_parse_service.set_technical_appendix_asset_selected",
        return_value=selection_result,
    ), patch(
        "app.services.bid_parse_service.enqueue_generation_job",
        return_value=type("Enqueue", (), {"queued": True, "job_id": "JOB-1", "locked": False, "unavailable": False})(),
    ) as enqueue_job:
        result = asyncio.run(service.approve_appendix_asset("PRJ-TECH-001", "APPX-A", {"approved": True}))

    enqueue_job.assert_not_called()
    assert "parseResult" not in result
    assert result == {
        "message": "已更新附表素材选择。",
        "selectedCount": 1,
        "appendixCount": 1,
    }


def test_technical_parse_job_does_not_archive_appendices_before_participation() -> None:
    """解析异步化后，执行链路收敛到 execute_s1_parse_job：未参与投标前只物化附表资产，不归档入库。"""

    from app.services.bid_parse_service import BidParseService

    project = {
        "id": "PRJ-TECH-001",
        "bidType": "技术标",
        "name": "技术标附表入库测试",
    }

    class _TechnicalProjectService:
        bid_type = "技术标"
        not_found_message = "技术标项目不存在。"
        wrong_type_message = "该接口仅支持技术标项目。"

        @staticmethod
        def ensure_project(project_id: str) -> dict[str, object]:
            assert project_id == project["id"]
            return project

    service = BidParseService(_TechnicalProjectService(), "/api/technical")
    tender_files = [{"id": "TEN-1", "path": "tender.docx"}]
    parse_result = {"status": "completed", "structured": {"appendices": []}}
    materialized_result = {
        "status": "completed",
        "structured": {
            "appendices": [
                {
                    "id": "APPX-0001",
                    "title": "附表A.1 投标机型总方案信息表",
                    "docxPath": "generated.docx",
                }
            ]
        },
    }

    with patch.object(
        service,
        "start_parse_progress",
    ), patch.object(service, "update_parse_progress"), patch.object(
        service,
        "raise_if_parse_cancel_requested",
    ), patch.object(service, "is_parse_cancel_requested", return_value=False), patch.object(
        service,
        "complete_parse",
        return_value=parse_result,
    ), patch.object(
        service,
        "_materialize_completed_parse_result",
        return_value=parse_result,
    ), patch.object(
        service,
        "_promote_completed_parse_if_participating",
        side_effect=lambda _project_id, payload: payload,
    ), patch.object(service, "finalize_parse_progress") as finalize_mock, patch(
        "app.services.bid_parse_service.parse_tender_documents",
        return_value=({"extractedCount": 1, "appendixCount": 1}, {}),
    ), patch(
        "app.services.bid_parse_service.materialize_parse_appendix_docx_assets",
        return_value=materialized_result,
    ), patch(
        "app.services.bid_parse_service.sync_technical_parse_appendices",
        new=AsyncMock(return_value={"status": "synced", "syncedCount": 1}),
        create=True,
    ) as sync_appendices:
        service.execute_s1_parse_job(
            str(project["id"]),
            {
                "__bidType": "技术标",
                "origin": "upload",
                "tenderFiles": tender_files,
                "templateFiles": [],
            },
        )

    finalize_mock.assert_called_once()
    finalized_result = finalize_mock.call_args[0][1]
    assert finalized_result["structured"]["appendices"] == materialized_result["structured"]["appendices"]
    sync_appendices.assert_not_awaited()


def test_technical_project_confirmation_archives_appendices_with_final_material_identity() -> None:
    from app.services.bid_project_service import BidProjectService

    project_id = "PRJ-TECH-001"
    parse_result = {
        "status": "completed",
        "structured": {
            "appendices": [
                {
                    "id": "APPX-0001",
                    "title": "附表A.1 投标机型总方案信息表",
                    "docxPath": "generated.docx",
                }
            ]
        },
    }
    runtime_project = {
        "id": project_id,
        "bidType": "技术标",
        "materialProjectMode": "library",
        "materialProjectId": "MAT-FINAL-001",
        "parse_result": parse_result,
    }
    updated_project = {
        "id": project_id,
        "bidType": "技术标",
        "materialProjectId": "MAT-FINAL-001",
        "reviewDecision": "participate",
    }
    service = BidProjectService(
        bid_type="技术标",
        not_found_message="技术标项目不存在。",
        wrong_type_message="该接口仅支持技术标项目。",
        delete_message="技术标项目已删除",
        sync_technical_parse_assets=True,
    )

    with patch(
        "app.services.bid_project_service.update_workspace_project",
        return_value=updated_project,
    ), patch.object(
        service,
        "ensure_project",
        return_value=runtime_project,
    ), patch(
        "app.services.bid_project_service.sync_technical_parse_appendices",
        new=AsyncMock(return_value={"status": "synced", "syncedCount": 1, "targetPath": "技术标/项目定制/MAT-FINAL-001"}),
        create=True,
    ) as sync_appendices, patch(
        "app.services.bid_project_service.persist_technical_parse_result",
        return_value=parse_result,
    ) as persist_parse_result:
        result = asyncio.run(
            service.update(
                project_id,
                {
                    "reviewDecision": "participate",
                    "materialProjectMode": "library",
                    "materialProjectId": "MAT-FINAL-001",
                },
            )
        )

    sync_appendices.assert_awaited_once()
    sync_project, synced_parse_result = sync_appendices.await_args.args
    assert sync_project["materialProjectMode"] == "library"
    assert sync_project["materialProjectId"] == "MAT-FINAL-001"
    assert sync_project.get("reviewDecision") != "participate"
    assert synced_parse_result is parse_result
    persist_parse_result.assert_called_once_with(project_id, parse_result)
    assert result["technicalParseAssetSync"] == {
        "status": "synced",
        "syncedCount": 1,
        "targetPath": "技术标/项目定制/MAT-FINAL-001",
    }


def test_technical_project_confirmation_persists_sync_state_after_failure() -> None:
    from app.services.bid_project_service import BidProjectService
    from app.services.technical_parse_assets import TechnicalParseAssetError

    project_id = "PRJ-TECH-001"
    parse_result = {
        "status": "completed",
        "structured": {"appendices": [{"id": "APPX-A", "selectedForMaterial": True}]},
    }
    runtime_project = {
        "id": project_id,
        "bidType": "技术标",
        "materialProjectId": "MAT-FINAL-001",
        "parse_result": parse_result,
    }
    updated_project = {
        "id": project_id,
        "bidType": "技术标",
        "reviewDecision": "participate",
    }
    service = BidProjectService(
        bid_type="技术标",
        not_found_message="技术标项目不存在。",
        wrong_type_message="该接口仅支持技术标项目。",
        delete_message="技术标项目已删除",
        sync_technical_parse_assets=True,
    )

    async def fail_after_manifest_update(_project, payload):
        payload["structured"]["technicalAppendixMaterialSync"] = {
            "items": [{"appendixId": "APPX-A", "materialId": "RAW-A", "name": "附表A.docx"}]
        }
        raise TechnicalParseAssetError("索引校验失败")

    with patch(
        "app.services.bid_project_service.update_workspace_project",
        return_value=updated_project,
    ), patch.object(
        service,
        "ensure_project",
        return_value=runtime_project,
    ), patch(
        "app.services.bid_project_service.sync_technical_parse_appendices",
        side_effect=fail_after_manifest_update,
    ), patch(
        "app.services.bid_project_service.persist_technical_parse_result",
        return_value=parse_result,
    ) as persist_parse_result:
        with pytest.raises(TechnicalParseAssetError, match="索引校验失败"):
            asyncio.run(service.update(project_id, {"reviewDecision": "participate"}))

    persist_parse_result.assert_called_once_with(project_id, parse_result)


def test_technical_project_confirmation_failure_does_not_persist_participate() -> None:
    from app.services.bid_project_service import BidProjectService
    from app.services.technical_parse_assets import TechnicalParseAssetError

    project_id = "PRJ-TECH-001"
    runtime_project = {
        "id": project_id,
        "bidType": "技术标",
        "name": "华能100MW风电项目",
        "reviewDecision": "pending",
        "parse_result": {"status": "completed", "structured": {"appendices": []}},
    }
    service = BidProjectService(
        bid_type="技术标",
        not_found_message="技术标项目不存在。",
        wrong_type_message="该接口仅支持技术标项目。",
        delete_message="技术标项目已删除",
        sync_technical_parse_assets=True,
    )

    with patch(
        "app.services.bid_project_service.update_workspace_project",
        return_value=runtime_project,
    ) as update_project, patch.object(
        service,
        "ensure_project",
        return_value=runtime_project,
    ), patch(
        "app.services.bid_project_service.sync_technical_parse_appendices",
        new=AsyncMock(side_effect=TechnicalParseAssetError("索引校验失败")),
    ), patch(
        "app.services.bid_project_service.persist_technical_parse_result",
        return_value=runtime_project["parse_result"],
    ):
        with pytest.raises(TechnicalParseAssetError, match="索引校验失败"):
            asyncio.run(service.update(project_id, {"reviewDecision": "participate"}))

    update_project.assert_not_called()


def test_participated_project_rename_does_not_bootstrap_stable_material_folder() -> None:
    from app.services.bid_project_service import BidProjectService

    project_id = "PRJ-TECH-001"
    runtime_project = {
        "id": project_id,
        "bidType": "技术标",
        "name": "旧项目名称",
        "reviewDecision": "participate",
    }
    updated_project = {**runtime_project, "name": "新项目名称"}
    bootstrap_material_folder = AsyncMock()
    service = BidProjectService(
        bid_type="技术标",
        not_found_message="技术标项目不存在。",
        wrong_type_message="该接口仅支持技术标项目。",
        delete_message="技术标项目已删除",
        bootstrap_material_folder=bootstrap_material_folder,
    )

    with patch.object(service, "ensure_project", return_value=runtime_project), patch(
        "app.services.bid_project_service.update_workspace_project",
        return_value=updated_project,
    ):
        result = asyncio.run(service.update(project_id, {"name": "新项目名称"}))

    bootstrap_material_folder.assert_not_awaited()
    assert "materialFolderBootstrap" not in result


def test_technical_project_confirmation_bootstraps_stable_material_folder() -> None:
    from app.services.bid_project_service import BidProjectService

    project_id = "PRJ-TECH-001"
    bootstrap_material_folder = AsyncMock(
        return_value={
            "payload": {
                "projectId": "MAT-FINAL-001",
                "path": "技术标/项目定制/MAT-FINAL-001",
            }
        }
    )
    service = BidProjectService(
        bid_type="技术标",
        not_found_message="技术标项目不存在。",
        wrong_type_message="该接口仅支持技术标项目。",
        delete_message="技术标项目已删除",
        bootstrap_material_folder=bootstrap_material_folder,
    )
    updated_project = {
        "id": project_id,
        "bidType": "技术标",
        "name": "华能100MW风电项目",
        "materialProjectId": "MAT-FINAL-001",
        "reviewDecision": "participate",
    }

    with patch(
        "app.services.bid_project_service.update_workspace_project",
        return_value=updated_project,
    ), patch.object(service, "ensure_project", return_value=updated_project):
        result = asyncio.run(
            service.update(
                project_id,
                {
                    "name": "华能100MW风电项目",
                    "materialProjectId": "MAT-FINAL-001",
                    "reviewDecision": "participate",
                },
            )
        )

    bootstrap_material_folder.assert_awaited_once_with("MAT-FINAL-001")
    assert result["materialFolderBootstrap"] == {
        "status": "ok",
        "projectId": "MAT-FINAL-001",
        "path": "技术标/项目定制/MAT-FINAL-001",
    }
