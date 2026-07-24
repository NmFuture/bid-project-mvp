from __future__ import annotations

from typing import Any, Callable

from app.services.business_assembly import assemble_business_bid_for_project_with_progress


def generate_business_draft_for_project(
    project_id: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return generate_business_draft_for_project_with_progress(project_id, data)


def generate_business_draft_for_project_with_progress(
    project_id: str,
    data: dict[str, Any] | None = None,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    return assemble_business_bid_for_project_with_progress(project_id, data, progress_callback)
