from __future__ import annotations

from app.services.bid_type import BUSINESS_BID_TYPE
from app.services.peripheral import PeripheralError
from app.services.workspace_project_access import (
    get_workspace_project_runtime_state,
    persist_workspace_project_state,
    require_workspace_project_for_update,
)


def _business_project_not_found(project_id: str) -> PeripheralError:
    return PeripheralError(404, "项目不存在。", "BUSINESS_PROJECT_NOT_FOUND")


def _business_project_required(project_id: str) -> PeripheralError:
    return PeripheralError(400, "该接口仅支持商务标项目。", "BUSINESS_PROJECT_REQUIRED")


def get_business_gap_project_runtime_state(project_id: str) -> dict[str, Any]:
    return get_workspace_project_runtime_state(
        project_id,
        bid_type=BUSINESS_BID_TYPE,
        not_found_error=_business_project_not_found,
        wrong_type_error=_business_project_required,
    )


def require_business_gap_project_for_update(project_id: str) -> dict[str, Any]:
    return require_workspace_project_for_update(
        project_id,
        bid_type=BUSINESS_BID_TYPE,
        not_found_error=_business_project_not_found,
        wrong_type_error=_business_project_required,
    )


def persist_business_gap_project(project: dict[str, Any]) -> None:
    persist_workspace_project_state(project)
