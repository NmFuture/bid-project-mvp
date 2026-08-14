from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


def _project() -> dict:
    return {
        "id": "PRJ-TECH-001",
        "bidType": "技术标",
        "reviewDecision": "participate",
        "parse_result": {
            "status": "completed",
            "structured": {
                "appendices": [
                    {"id": "APPX-A", "selectedForMaterial": True},
                    {"id": "APPX-B", "selectedForMaterial": False},
                ]
            },
        },
    }


def test_schedule_runs_appendix_sync_and_persists_success_state() -> None:
    from app.services.technical_parse_asset_sync_job import schedule_technical_parse_asset_sync

    project = _project()
    captured: dict[str, object] = {}

    def capture_job(name, coro_factory):
        captured["name"] = name
        captured["run"] = coro_factory
        return {"status": "running"}

    with patch(
        "app.services.technical_parse_asset_sync_job.require_any_workspace_project_for_update",
        return_value=project,
    ), patch(
        "app.services.technical_parse_asset_sync_job.persist_workspace_project_fields",
    ) as persist_fields, patch(
        "app.services.technical_parse_asset_sync_job.persist_technical_parse_result",
        return_value=project["parse_result"],
    ) as persist_parse_result, patch(
        "app.services.technical_parse_asset_sync_job.sync_technical_parse_appendices",
        new=AsyncMock(
            return_value={
                "status": "synced",
                "selectedCount": 1,
                "syncedCount": 1,
                "uploadedCount": 1,
                "deletedCount": 0,
            }
        ),
    ), patch(
        "app.services.technical_parse_asset_sync_job.start_job",
        side_effect=capture_job,
    ):
        state = schedule_technical_parse_asset_sync(project["id"])
        result = asyncio.run(captured["run"]())

    assert captured["name"] == "technical-parse-asset-sync:PRJ-TECH-001"
    assert state["status"] == "running"
    assert state["selectedCount"] == 1
    assert result["syncedCount"] == 1
    assert project["technicalParseAssetSyncState"]["status"] == "succeeded"
    assert project["technicalParseAssetSyncState"]["syncedCount"] == 1
    persist_parse_result.assert_called_once()
    assert persist_fields.call_count >= 2


def test_failed_appendix_sync_persists_checkpoint_and_can_be_retried() -> None:
    from app.services.technical_parse_asset_sync_job import schedule_technical_parse_asset_sync

    project = _project()
    runs = []

    def capture_job(_name, coro_factory):
        runs.append(coro_factory)
        return {"status": "running"}

    async def fail_after_checkpoint(_project_payload, parse_result):
        parse_result["structured"]["technicalAppendixMaterialSync"] = {
            "items": [{"appendixId": "APPX-A", "materialId": "RAW-A"}]
        }
        raise RuntimeError("索引校验失败")

    with patch(
        "app.services.technical_parse_asset_sync_job.require_any_workspace_project_for_update",
        return_value=project,
    ), patch(
        "app.services.technical_parse_asset_sync_job.persist_workspace_project_fields",
    ), patch(
        "app.services.technical_parse_asset_sync_job.persist_technical_parse_result",
        return_value=project["parse_result"],
    ) as persist_parse_result, patch(
        "app.services.technical_parse_asset_sync_job.sync_technical_parse_appendices",
        new=AsyncMock(side_effect=fail_after_checkpoint),
    ), patch(
        "app.services.technical_parse_asset_sync_job.start_job",
        side_effect=capture_job,
    ):
        schedule_technical_parse_asset_sync(project["id"])
        with pytest.raises(RuntimeError, match="索引校验失败"):
            asyncio.run(runs[0]())

        assert project["technicalParseAssetSyncState"]["status"] == "failed"
        assert project["technicalParseAssetSyncState"]["error"] == "索引校验失败"
        assert persist_parse_result.call_args.args[1]["structured"]["technicalAppendixMaterialSync"]

        schedule_technical_parse_asset_sync(project["id"])

    assert len(runs) == 2


def test_retry_route_validates_project_and_schedules_sync() -> None:
    from app.api.routes.technical import retry_technical_parse_asset_sync

    with patch(
        "app.api.routes.technical.technical_project_service.ensure_project",
        return_value={"id": "PRJ-TECH-001", "bidType": "技术标"},
    ) as ensure_project, patch(
        "app.api.routes.technical.schedule_technical_parse_asset_sync",
        return_value={"status": "running", "selectedCount": 1},
    ) as schedule:
        result = asyncio.run(retry_technical_parse_asset_sync("PRJ-TECH-001"))

    ensure_project.assert_called_once_with("PRJ-TECH-001")
    schedule.assert_called_once_with("PRJ-TECH-001")
    assert result["status"] == "running"


def test_project_detail_exposes_parse_asset_sync_state() -> None:
    from app.services.bid_project_state import project_detail_state

    project = {
        "files": [],
        "templateFiles": [],
        "isKeyAccount": False,
        "keyAccountId": "",
        "technicalParseAssetSyncState": {
            "status": "failed",
            "error": "索引校验失败",
        },
    }
    with patch(
        "app.services.bid_project_state.project_summary_state",
        return_value={"id": "PRJ-TECH-001"},
    ):
        detail = project_detail_state(project)

    assert detail["technicalParseAssetSyncState"]["status"] == "failed"
    assert detail["technicalParseAssetSyncState"]["error"] == "索引校验失败"


def test_stale_running_state_is_recovered_as_retryable_failure() -> None:
    from app.services.technical_parse_asset_sync_job import recover_stale_technical_parse_asset_sync

    project = _project()
    project["technicalParseAssetSyncState"] = {
        "status": "running",
        "selectedCount": 1,
        "startedAt": "2026-08-14T08:00:00Z",
    }
    with patch(
        "app.services.technical_parse_asset_sync_job.require_any_workspace_project_for_update",
        return_value=project,
    ), patch(
        "app.services.technical_parse_asset_sync_job.is_job_active",
        return_value=False,
    ), patch(
        "app.services.technical_parse_asset_sync_job.persist_workspace_project_fields",
    ) as persist_fields:
        state = recover_stale_technical_parse_asset_sync(project["id"])

    assert state["status"] == "failed"
    assert "重试" in state["message"]
    assert state["error"]
    persist_fields.assert_called_once()


def test_project_get_recovers_stale_parse_asset_sync_before_serializing() -> None:
    from app.services.bid_project_service import BidProjectService

    service = BidProjectService(
        bid_type="技术标",
        not_found_message="技术标项目不存在。",
        wrong_type_message="该接口仅支持技术标项目。",
        delete_message="技术标项目已删除",
        sync_technical_parse_assets=True,
    )
    with patch.object(service, "ensure_project", return_value=_project()), patch(
        "app.services.bid_project_service.recover_stale_technical_parse_asset_sync",
    ) as recover, patch(
        "app.services.bid_project_service.get_workspace_project_detail",
        return_value={"id": "PRJ-TECH-001"},
    ):
        service.get("PRJ-TECH-001")

    recover.assert_called_once_with("PRJ-TECH-001")
