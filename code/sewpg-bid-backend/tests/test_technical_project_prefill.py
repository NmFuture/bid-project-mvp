from __future__ import annotations

from app.services import parsing as parsing_service
from app.services.bid_parse_service import BidParseService
from app.services.bid_parse_state import complete_parse_state
from app.services.bid_project_state import create_project_state, project_detail_state, update_project_state


def _project_basics(*rows: dict) -> dict:
    return {"fieldGroups": {"projectBasics": list(rows)}}


def test_technical_project_prefill_maps_positive_parse_fields_with_evidence() -> None:
    helper = getattr(parsing_service, "_project_basics_project_prefill", None)
    assert callable(helper)

    prefill = helper(
        _project_basics(
            {
                "key": "projectName",
                "status": "found",
                "value": "华能甘肃100MW风电项目",
                "evidenceIds": ["TEN-1:B000001"],
            },
            {
                "fieldKey": "tenderNo",
                "status": "partial",
                "value": "HN-GS-2026-001",
                "evidenceIds": ["TEN-1:B000002"],
            },
            {
                "key": "bidDeadline",
                "status": "found",
                "value": "2026-08-06 10:00",
                "evidenceIds": ["TEN-1:B000003"],
            },
        )
    )

    assert prefill == {
        "name": "华能甘肃100MW风电项目",
        "projectCode": "HN-GS-2026-001",
        "endDate": "2026-08-06",
        "deadline": "2026-08-06",
        "sources": {
            "name": {
                "fieldKey": "projectName",
                "status": "found",
                "evidenceIds": ["TEN-1:B000001"],
            },
            "projectCode": {
                "fieldKey": "tenderNo",
                "status": "partial",
                "evidenceIds": ["TEN-1:B000002"],
            },
            "endDate": {
                "fieldKey": "bidDeadline",
                "status": "found",
                "evidenceIds": ["TEN-1:B000003"],
            },
        },
    }


def test_technical_project_prefill_ignores_missing_values() -> None:
    helper = getattr(parsing_service, "_project_basics_project_prefill", None)
    assert callable(helper)

    prefill = helper(
        _project_basics(
            {"key": "projectName", "status": "missing", "value": "当前文件未提及项目名称"},
            {"key": "tenderNo", "status": "needs_spec", "value": "建议补充招标公告"},
            {"key": "bidDeadline", "status": "found", "value": "未明确"},
        )
    )

    assert prefill == {}


def test_complete_parse_state_exposes_project_prefill_without_replacing_defaults() -> None:
    project = create_project_state(
        "PRJ-0001",
        {
            "name": "技术标解析暂存-20260717-1530",
            "bidType": "技术标",
            "isParseDraft": True,
        },
    )
    prefill = {
        "name": "华能甘肃100MW风电项目",
        "projectCode": "HN-GS-2026-001",
        "endDate": "2026-08-06",
        "deadline": "2026-08-06",
    }

    result = complete_parse_state(
        project,
        [],
        [],
        parse_storage={"structured": {}, "items": [], "documents": [], "projectPrefill": prefill},
    )

    assert result["projectPrefill"] == prefill
    assert project["name"] == "技术标解析暂存-20260717-1530"
    assert project["projectCode"] == "PRJ-0001"


def test_parse_draft_marker_is_returned_and_cleared_on_confirmation() -> None:
    project = create_project_state(
        "PRJ-0002",
        {
            "name": "技术标解析暂存-20260717-1540",
            "bidType": "技术标",
            "isParseDraft": True,
        },
    )

    assert project_detail_state(project)["isParseDraft"] is True

    update_project_state(project, project["id"], {"isParseDraft": False})

    assert project_detail_state(project)["isParseDraft"] is False


def test_existing_technical_parse_result_backfills_project_prefill() -> None:
    class ExistingTechnicalProjectService:
        bid_type = "技术标"

        @staticmethod
        def ensure_project(_project_id: str) -> dict:
            return {
                "parse_result": {
                    "status": "completed",
                    "structured": _project_basics(
                        {"key": "projectName", "status": "found", "value": "存量解析项目"},
                        {"key": "tenderNo", "status": "found", "value": "OLD-2026-001"},
                    ),
                }
            }

    service = BidParseService(ExistingTechnicalProjectService(), "/api/technical")

    result = service.parse_result("PRJ-OLD")

    assert result["projectPrefill"]["name"] == "存量解析项目"
    assert result["projectPrefill"]["projectCode"] == "OLD-2026-001"
