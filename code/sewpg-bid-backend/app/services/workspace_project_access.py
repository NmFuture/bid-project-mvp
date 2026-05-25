from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.bid_type import require_bid_type
from app.services.bid_parse_state import ensure_parse_progress_state
from app.services.bid_project_state import project_template_fallback_context, update_template_fallback_state
from app.services.store import store


ProjectErrorFactory = Callable[[str], Exception]


def ensure_workspace_project_type(
    project: dict[str, Any],
    *,
    bid_type: str,
    wrong_type_error: ProjectErrorFactory,
) -> dict[str, Any]:
    expected_bid_type = require_bid_type(
        bid_type,
        error_message="workspace 项目访问必须显式传入技术标或商务标。",
    )
    actual_bid_type = require_bid_type(
        project.get("bidType"),
        error_message="项目必须显式传入技术标或商务标。",
    )
    if actual_bid_type != expected_bid_type:
        raise wrong_type_error(str(project.get("id") or ""))
    return project


def get_workspace_project_runtime_state(
    project_id: str,
    *,
    bid_type: str,
    not_found_error: ProjectErrorFactory,
    wrong_type_error: ProjectErrorFactory,
) -> dict[str, Any]:
    try:
        project = store.get_project_runtime_state(project_id)
    except KeyError as exc:
        raise not_found_error(project_id) from exc
    return ensure_workspace_project_type(project, bid_type=bid_type, wrong_type_error=wrong_type_error)


def get_any_workspace_project_runtime_state(
    project_id: str,
    *,
    not_found_error: ProjectErrorFactory,
) -> dict[str, Any]:
    try:
        return store.get_project_runtime_state(project_id)
    except KeyError as exc:
        raise not_found_error(project_id) from exc


def list_workspace_projects(
    *,
    status: str = "",
    bid_type: str = "",
    date_range: str = "",
    page: int = 1,
    page_size: int = 12,
) -> dict[str, Any]:
    return store.list_projects(
        status=status,
        bid_type=bid_type,
        date_range=date_range,
        page=page,
        page_size=page_size,
    )


def create_workspace_project(data: dict[str, Any]) -> dict[str, Any]:
    return store.create_project(data)


def get_workspace_project_detail(project_id: str, *, not_found_error: ProjectErrorFactory) -> dict[str, Any]:
    try:
        return store.get_project(project_id)
    except KeyError as exc:
        raise not_found_error(project_id) from exc


def update_workspace_project(
    project_id: str,
    data: dict[str, Any],
    *,
    not_found_error: ProjectErrorFactory,
) -> dict[str, Any]:
    try:
        return store.update_project(project_id, data)
    except KeyError as exc:
        raise not_found_error(project_id) from exc


def delete_workspace_project(project_id: str, *, not_found_error: ProjectErrorFactory) -> None:
    try:
        store.delete_project(project_id)
    except KeyError as exc:
        raise not_found_error(project_id) from exc


def workspace_template_fallback_context(project_id: str, *, not_found_error: ProjectErrorFactory) -> dict[str, Any]:
    try:
        project = store.get_project_runtime_state(project_id)
    except KeyError as exc:
        raise not_found_error(project_id) from exc
    return project_template_fallback_context(project_id, project)


def update_workspace_template_fallback(
    project_id: str,
    data: dict[str, Any],
    *,
    not_found_error: ProjectErrorFactory,
) -> dict[str, Any]:
    try:
        project = store.require_project_for_update(project_id)
    except KeyError as exc:
        raise not_found_error(project_id) from exc
    update_template_fallback_state(project, data)
    store.persist_project_state(project)
    return project_template_fallback_context(project_id, project)


def workspace_parse_progress(project_id: str, *, not_found_error: ProjectErrorFactory) -> dict[str, Any]:
    try:
        project = store.require_project_for_update(project_id)
    except KeyError as exc:
        raise not_found_error(project_id) from exc
    existed = isinstance(project.get("parse_progress"), dict)
    progress = ensure_parse_progress_state(project)
    if not existed:
        store.persist_project_state(project)
    return progress


def workspace_project_stages(project_id: str, *, not_found_error: ProjectErrorFactory) -> list[dict[str, Any]]:
    try:
        return store.get_stages(project_id)
    except KeyError as exc:
        raise not_found_error(project_id) from exc


def update_workspace_project_stage(
    project_id: str,
    stage: int,
    data: dict[str, Any],
    *,
    not_found_error: ProjectErrorFactory,
) -> dict[str, Any]:
    try:
        return store.update_stage(project_id, stage, data)
    except KeyError as exc:
        raise not_found_error(project_id) from exc


def require_workspace_project_for_update(
    project_id: str,
    *,
    bid_type: str,
    not_found_error: ProjectErrorFactory,
    wrong_type_error: ProjectErrorFactory,
) -> dict[str, Any]:
    try:
        project = store.require_project_for_update(project_id)
    except KeyError as exc:
        raise not_found_error(project_id) from exc
    return ensure_workspace_project_type(project, bid_type=bid_type, wrong_type_error=wrong_type_error)


def require_any_workspace_project_for_update(
    project_id: str,
    *,
    not_found_error: ProjectErrorFactory,
) -> dict[str, Any]:
    try:
        return store.require_project_for_update(project_id)
    except KeyError as exc:
        raise not_found_error(project_id) from exc


def persist_workspace_project_state(project: dict[str, Any]) -> None:
    store.persist_project_state(project)
