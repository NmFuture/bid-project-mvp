from __future__ import annotations

from typing import Any, Callable

from app.services.tech_assembly import assemble_tech_bid_for_project_with_progress


def generate_draft_for_project(project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return generate_draft_for_project_with_progress(project_id, data)


def generate_draft_for_project_with_progress(
    project_id: str,
    data: dict[str, Any] | None = None,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    """S7 now assembles the technical bid Word from S2 JSON and materials."""
    return assemble_tech_bid_for_project_with_progress(project_id, data, progress_callback)
