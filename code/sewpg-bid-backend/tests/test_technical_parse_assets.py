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
    assert upload_calls[0]["on_conflict"] == "version"
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


@pytest.mark.parametrize("workflow", ["run_without_upload", "upload_and_parse"])
def test_technical_parse_workflows_do_not_archive_appendices_before_participation(workflow: str) -> None:
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

    with patch.object(service, "parse_inputs", return_value=(tender_files, [])), patch.object(
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
    ), patch.object(service, "finalize_parse_progress"), patch(
        "app.services.bid_parse_service._parse_tender_documents_async",
        new=AsyncMock(return_value=({"extractedCount": 1, "appendixCount": 1}, {})),
    ), patch(
        "app.services.bid_parse_service.materialize_parse_appendix_docx_assets",
        return_value=materialized_result,
    ), patch(
        "app.services.bid_parse_service.sync_technical_parse_appendices",
        new=AsyncMock(return_value={"status": "synced", "syncedCount": 1}),
        create=True,
    ) as sync_appendices:
        if workflow == "run_without_upload":
            result = asyncio.run(service.run_without_upload(str(project["id"])))
        else:
            result = asyncio.run(service.upload_and_parse(str(project["id"])))

    assert result["structured"]["appendices"] == materialized_result["structured"]["appendices"]
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
    ) as sync_appendices:
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

    sync_appendices.assert_awaited_once_with(runtime_project, parse_result)
    assert result["technicalParseAssetSync"] == {
        "status": "synced",
        "syncedCount": 1,
        "targetPath": "技术标/项目定制/MAT-FINAL-001",
    }
