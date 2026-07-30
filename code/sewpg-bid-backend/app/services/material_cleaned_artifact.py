from __future__ import annotations

from typing import Any


def cleaned_artifact_is_current(current_version: int, ext_fields: dict[str, Any] | None) -> bool:
    ext = ext_fields if isinstance(ext_fields, dict) else {}
    if not str(ext.get("cleanedMinioKey") or ""):
        return False
    source_version = ext.get("cleanedSourceVersion")
    if source_version is None or source_version == "":
        return True
    try:
        return int(source_version) == int(current_version)
    except (TypeError, ValueError):
        return False
