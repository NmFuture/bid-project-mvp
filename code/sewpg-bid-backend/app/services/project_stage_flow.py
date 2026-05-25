from __future__ import annotations

import copy
from typing import Any

from app.services.bid_type import BUSINESS_BID_TYPE, require_bid_type


STAGE_SCHEME = "S0_S6"
MAX_PROJECT_STAGE = 6

TECHNICAL_STAGE_NAMES = {
    1: "模板与目录",
    2: "审核目录",
    3: "缺口处理",
    4: "生成标书",
    5: "共创",
    6: "导出",
}

BUSINESS_STAGE_LABELS = {
    1: "模板与目录",
    2: "审核目录",
    3: "素材匹配",
    4: "素材匹配",
    5: "共创导出",
    6: "共创导出",
}

TECHNICAL_STAGE_PROGRESS_GROUPS = [
    {"id": 1, "name": "模板与目录", "routeStageId": 1, "isHuman": False},
    {"id": 2, "name": "审核目录", "routeStageId": 2, "isHuman": True},
    {"id": 3, "name": "缺口处理", "routeStageId": 3, "isHuman": True},
    {"id": 4, "name": "生成标书", "routeStageId": 4, "isHuman": False},
    {"id": 5, "name": "共创", "routeStageId": 5, "isHuman": True},
    {"id": 6, "name": "导出", "routeStageId": 6, "isHuman": False},
]

BUSINESS_STAGE_PROGRESS_GROUPS = [
    {"id": 1, "name": "模板与目录", "routeStageId": 1, "isHuman": False, "sourceStages": [1]},
    {"id": 2, "name": "审核目录", "routeStageId": 2, "isHuman": True, "sourceStages": [2]},
    {"id": 3, "name": "素材匹配", "routeStageId": 3, "isHuman": True, "sourceStages": [3, 4]},
    {"id": 4, "name": "共创导出", "routeStageId": 5, "isHuman": True, "sourceStages": [5, 6]},
]

LEGACY_STAGE_TO_CURRENT = {
    0: 1,
    1: 1,
    2: 1,
    3: 2,
    4: 3,
    5: 3,
    6: 3,
    7: 4,
    8: 4,
    9: 5,
    10: 6,
}


def normalize_project_stage_value(value: Any, *, scheme: str = "") -> int:
    try:
        raw_stage = int(value or 1)
    except (TypeError, ValueError):
        raw_stage = 1
    if str(scheme or "") == STAGE_SCHEME:
        return max(1, min(MAX_PROJECT_STAGE, raw_stage))
    return LEGACY_STAGE_TO_CURRENT.get(raw_stage, max(1, min(MAX_PROJECT_STAGE, raw_stage)))


def normalize_project_stage_request(value: Any) -> int:
    try:
        raw_stage = int(value or 1)
    except (TypeError, ValueError):
        raw_stage = 1
    if raw_stage > MAX_PROJECT_STAGE:
        return LEGACY_STAGE_TO_CURRENT.get(raw_stage, MAX_PROJECT_STAGE)
    return max(1, min(MAX_PROJECT_STAGE, raw_stage))


def _project_bid_type(project: dict[str, Any]) -> str:
    return require_bid_type(
        project.get("bidType"),
        error_message="项目阶段必须显式传入技术标或商务标。",
    )


def should_skip_technical_gap_stage(project: dict[str, Any]) -> bool:
    if _project_bid_type(project) == BUSINESS_BID_TYPE:
        return False
    outline_state = project.get("outline_state") if isinstance(project.get("outline_state"), dict) else {}
    return str(outline_state.get("reviewStatus") or "") == "confirmed"


def project_stage_label(project: dict[str, Any]) -> str:
    current_stage = int(project.get("currentStage") or 1)
    if _project_bid_type(project) == BUSINESS_BID_TYPE:
        return BUSINESS_STAGE_LABELS.get(current_stage, TECHNICAL_STAGE_NAMES.get(current_stage, "未知阶段"))
    return TECHNICAL_STAGE_NAMES.get(current_stage, "未知阶段")


def project_progress_stages(project: dict[str, Any]) -> list[dict[str, Any]]:
    current_stage = normalize_project_stage_value(project.get("currentStage"), scheme=STAGE_SCHEME)
    if _project_bid_type(project) == BUSINESS_BID_TYPE:
        return business_progress_stages(current_stage)
    return technical_progress_stages(
        current_stage,
        skip_gap_stage=should_skip_technical_gap_stage(project),
    )


def business_progress_stages(current_stage: int) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    active_display_id = 1
    for group in BUSINESS_STAGE_PROGRESS_GROUPS:
        source_stages = [int(item) for item in group.get("sourceStages", [])]
        if current_stage in source_stages:
            active_display_id = int(group["id"])
            break
        if source_stages and current_stage > max(source_stages):
            active_display_id = int(group["id"]) + 1
    for group in BUSINESS_STAGE_PROGRESS_GROUPS:
        stage_id = int(group["id"])
        if stage_id < active_display_id:
            status = "completed"
        elif stage_id == active_display_id:
            status = "active"
        else:
            status = "pending"
        stages.append(
            {
                "id": group["id"],
                "name": group["name"],
                "status": status,
                "isHuman": bool(group["isHuman"]),
                "routeStageId": group["routeStageId"],
                "sourceStages": copy.deepcopy(group.get("sourceStages") or []),
            }
        )
    return stages


def technical_progress_stages(current_stage: int, *, skip_gap_stage: bool = False) -> list[dict[str, Any]]:
    if skip_gap_stage and current_stage == 3:
        current_stage = 4
    stages: list[dict[str, Any]] = []
    for group in TECHNICAL_STAGE_PROGRESS_GROUPS:
        stage_id = int(group["id"])
        if skip_gap_stage and stage_id == 3:
            status = "completed"
        elif stage_id < current_stage:
            status = "completed"
        elif stage_id == current_stage:
            status = "active"
        else:
            status = "pending"
        stages.append(
            {
                "id": group["id"],
                "name": group["name"],
                "status": status,
                "isHuman": bool(group["isHuman"]),
                "routeStageId": group["routeStageId"],
                "isSkipped": bool(skip_gap_stage and stage_id == 3),
            }
        )
    return stages


def updated_project_stage_after_request(
    project: dict[str, Any],
    stage: int,
    status: str,
) -> int:
    normalized_stage = normalize_project_stage_request(stage)
    current_stage = normalize_project_stage_value(project.get("currentStage"), scheme=STAGE_SCHEME)
    if status == "completed":
        next_stage = normalized_stage + 1
        if normalized_stage == 2 and should_skip_technical_gap_stage(project):
            next_stage = 4
        return min(MAX_PROJECT_STAGE, max(current_stage, next_stage))
    if status == "active":
        if normalized_stage == 3 and should_skip_technical_gap_stage(project):
            normalized_stage = 4
        return max(1, min(MAX_PROJECT_STAGE, normalized_stage))
    return current_stage


def apply_confirmed_outline_stage(project: dict[str, Any]) -> None:
    if not should_skip_technical_gap_stage(project):
        return
    current_stage = normalize_project_stage_value(project.get("currentStage"), scheme=STAGE_SCHEME)
    project["currentStage"] = min(MAX_PROJECT_STAGE, max(current_stage, 4))
