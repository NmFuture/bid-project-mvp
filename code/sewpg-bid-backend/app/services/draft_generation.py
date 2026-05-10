from __future__ import annotations

from typing import Any, Callable

from app.services.business_assembly import assemble_business_bid_for_project_with_progress
from app.services.parse_profiles import normalize_bid_type
from app.services.store import store
from app.services.tech_assembly import assemble_tech_bid_for_project_with_progress


def generate_draft_for_project(project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return generate_draft_for_project_with_progress(project_id, data)


def generate_draft_for_project_with_progress(
    project_id: str,
    data: dict[str, Any] | None = None,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    """S4 assembles bid-specific Word output from the approved directory and materials."""
    project = store.get_project(project_id)
    if normalize_bid_type(str(project.get("bidType") or "")) == "商务标":
        return assemble_business_bid_for_project_with_progress(project_id, data, progress_callback)
    return assemble_tech_bid_for_project_with_progress(project_id, data, progress_callback)
