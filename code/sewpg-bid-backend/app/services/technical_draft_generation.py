from __future__ import annotations

from typing import Any, Callable

from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.tech_assembly import assemble_tech_bid_for_project_with_progress
from app.services.workspace_project_access import get_workspace_project_runtime_state


def generate_technical_draft_for_project(
    project_id: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return generate_technical_draft_for_project_with_progress(project_id, data)


def generate_technical_draft_for_project_with_progress(
    project_id: str,
    data: dict[str, Any] | None = None,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    get_workspace_project_runtime_state(
        project_id,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=KeyError,
        wrong_type_error=lambda _project_id: ValueError("技术标生成标书仅支持技术标项目。"),
    )
    return assemble_tech_bid_for_project_with_progress(project_id, data, progress_callback)
