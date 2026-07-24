from __future__ import annotations

import copy
from typing import Any

from app.services.bid_runtime_state import now_iso
from app.services.business_document_state import apply_business_document_format_state
from app.services.technical_document_state import apply_technical_document_format_state


def save_document_content_state(project: dict[str, Any], project_id: str, content: str) -> dict[str, Any]:
    state = project["document_state"]
    next_version = int(state["version"] or 1) + 1
    state["version"] = next_version
    state["lastSavedAt"] = now_iso()
    state["onlyoffice"]["documentKey"] = f"{project_id}-v{next_version}"
    state["fallback"]["content"] = content
    project["updatedAt"] = state["lastSavedAt"]
    return copy.deepcopy(state)


def force_save_document_state(project: dict[str, Any], project_id: str) -> dict[str, Any]:
    state = project["document_state"]
    next_version = int(state["version"] or 1) + 1
    state["version"] = next_version
    state["lastSavedAt"] = now_iso()
    state["onlyoffice"]["documentKey"] = f"{project_id}-v{next_version}"
    project["updatedAt"] = state["lastSavedAt"]
    return copy.deepcopy(state)


def apply_business_document_format_to_project(
    project: dict[str, Any],
    format_result: dict[str, Any],
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    state = apply_business_document_format_state(project, format_result, updated_at=updated_at or now_iso())
    return copy.deepcopy(state)


def apply_technical_document_format_to_project(
    project: dict[str, Any],
    format_result: dict[str, Any],
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    state = apply_technical_document_format_state(project, format_result, updated_at=updated_at or now_iso())
    return copy.deepcopy(state)


def final_document_state(project: dict[str, Any]) -> dict[str, Any]:
    state = project["document_state"]
    return {
        "ready": True,
        "fileName": state["fileName"],
        "fileType": state["fileType"],
        "fileUrl": "",
        "lastSavedAt": state["lastSavedAt"],
        "version": state["version"],
    }
