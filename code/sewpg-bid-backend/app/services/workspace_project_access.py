from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from app.services.bid_type import require_bid_type
from app.services.bid_parse_state import ensure_parse_progress_state
from app.services.bid_project_repository import ProjectConcurrentUpdateError, project_revision
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
    review_decision: str = "",
    date_range: str = "",
    page: int = 1,
    page_size: int = 12,
) -> dict[str, Any]:
    return store.list_projects(
        status=status,
        bid_type=bid_type,
        review_decision=review_decision,
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


def persist_workspace_project_fields(project: dict[str, Any], *fields: str) -> None:
    """只写回本次真正改动的顶层字段。

    调用方必须列全改动的字段：漏列的改动不会落库。宁可多列一个，也不要漏列。
    `updatedAt` 由这里统一带上，不必显式传。
    """
    store.persist_project_fields(project, (*fields, "updatedAt"))


def persist_workspace_project_state_checked(project: dict[str, Any]) -> None:
    """带并发校验的写回：库里版本仍是本次读到的版本才落库，否则抛冲突。"""
    store.persist_project_state_checked(project, project_revision(project))


def mutate_workspace_project(
    project_id: str,
    mutate: Callable[[dict[str, Any]], Any],
    *,
    bid_type: str,
    not_found_error: ProjectErrorFactory,
    wrong_type_error: ProjectErrorFactory,
    retries: int = 8,
    persist_when: Callable[[Any], bool] | None = None,
) -> Any:
    """读-改-写的原子封装：CAS 冲突时基于最新状态重放 `mutate`。

    `mutate` 必须只做状态改动，不能包含慢操作或不可重复的副作用（AI 填写、
    素材下载、文件写入）——那些要留在调用点外面先跑完，再把结果写进来。

    `persist_when` 按 `mutate` 的返回值判断是否需要落库，给只读路径（轮询接口
    顺带做的自愈修复）留出「没改动就不写」的空档，避免白白递增版本号。
    """
    last_error: ProjectConcurrentUpdateError | None = None
    for _ in range(max(1, retries)):
        project = require_workspace_project_for_update(
            project_id,
            bid_type=bid_type,
            not_found_error=not_found_error,
            wrong_type_error=wrong_type_error,
        )
        expected_rev = project_revision(project)
        # 内存后端下 require 返回的是 store 内的同一个 dict：任何一步失败都必须把它
        # 还原，否则未落库的半成品改动会留在进程内存里被后续请求读到。
        snapshot = copy.deepcopy(project)

        def restore() -> None:
            project.clear()
            project.update(snapshot)

        try:
            result = mutate(project)
        except Exception:
            restore()
            raise
        if persist_when is not None and not persist_when(result):
            return result
        try:
            store.persist_project_state_checked(project, expected_rev)
        except ProjectConcurrentUpdateError as exc:
            restore()
            last_error = exc
            continue
        except Exception:
            restore()
            raise
        return result
    raise last_error if last_error else RuntimeError(f"项目 {project_id} 写入重试失败。")
