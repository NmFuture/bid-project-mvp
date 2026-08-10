from __future__ import annotations

from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.peripheral import PeripheralError
from app.services.workspace_project_access import (
    get_workspace_project_runtime_state,
    mutate_workspace_project,
    persist_workspace_project_state_checked,
    require_workspace_project_for_update,
)


def _technical_project_not_found(project_id: str) -> PeripheralError:
    return PeripheralError(404, "技术标项目不存在。", "TECHNICAL_PROJECT_NOT_FOUND")


def _technical_project_required(project_id: str) -> PeripheralError:
    return PeripheralError(400, "该接口仅支持技术标项目。", "TECHNICAL_PROJECT_REQUIRED")


def get_technical_gap_project_runtime_state(project_id: str) -> dict[str, Any]:
    return get_workspace_project_runtime_state(
        project_id,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=_technical_project_not_found,
        wrong_type_error=_technical_project_required,
    )


def require_technical_gap_project_for_update(project_id: str) -> dict[str, Any]:
    return require_workspace_project_for_update(
        project_id,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=_technical_project_not_found,
        wrong_type_error=_technical_project_required,
    )


def persist_technical_gap_project(project: dict[str, Any]) -> None:
    """技术标项目写回，默认带并发校验。

    读到写之间若有其他进程（后台填写 worker、并行请求）写过同一项目，这里拒绝写入
    并抛 ``ProjectConcurrentUpdateError``，而不是整份覆盖把对方的改动静默吞掉。
    需要自动重放的路径改用 :func:`mutate_technical_gap_project`。
    """
    persist_workspace_project_state_checked(project)


def mutate_technical_gap_project(project_id: str, mutate, *, retries: int = 8, persist_when=None):
    """技术标项目的原子读-改-写；`mutate` 内只允许纯状态改动（可被重放）。"""
    return mutate_workspace_project(
        project_id,
        mutate,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=_technical_project_not_found,
        wrong_type_error=_technical_project_required,
        retries=retries,
        persist_when=persist_when,
    )
