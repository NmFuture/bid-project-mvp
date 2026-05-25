from __future__ import annotations

import copy
from typing import Any


def apply_business_document_format_state(
    project: dict[str, Any],
    format_result: dict[str, Any],
    *,
    updated_at: str,
) -> dict[str, Any]:
    state = project["document_state"]
    next_version = int(state.get("version") or 1) + 1
    state["version"] = next_version
    state["lastSavedAt"] = updated_at
    state.setdefault("onlyoffice", {})["documentKey"] = f"{project['id']}-v{next_version}"
    state["businessFormatPreset"] = str(format_result.get("preset") or "standard")
    state["businessFormatLabel"] = str(format_result.get("label") or "")
    state["businessFormatSummary"] = copy.deepcopy(format_result.get("summary") or {})
    fill_state = project.get("fill_state") if isinstance(project.get("fill_state"), dict) else {}
    fill_state["lastBusinessFormat"] = copy.deepcopy(format_result)
    project["fill_state"] = fill_state
    project["updatedAt"] = updated_at
    return state
