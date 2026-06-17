from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import submission_path


TARGET_KEYS = {"technicalInterpretation"}


def _empty() -> dict[str, Any]:
    return {
        "schemaVersion": "bid-tech-agentic-submissions-v1",
        "updatedAt": "",
        "targets": {},
    }


def load(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    path = submission_path(manifest_path, manifest)
    if not path.is_file():
        return _empty()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else _empty()


def save(manifest_path: Path, manifest: dict[str, Any], payload: dict[str, Any]) -> Path:
    path = submission_path(manifest_path, manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updatedAt"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def submit(manifest_path: Path, manifest: dict[str, Any], target_key: str, value: Any) -> dict[str, Any]:
    if target_key not in TARGET_KEYS:
        raise RuntimeError(f"unsupported targetKey: {target_key}")
    payload = load(manifest_path, manifest)
    payload.setdefault("targets", {})[target_key] = value
    path = save(manifest_path, manifest, payload)
    count = len(payload.get("targets") or {})
    return {
        "schemaVersion": "bid-tech-agentic-submit-v1",
        "status": "saved",
        "targetKey": target_key,
        "submissionPath": str(path),
        "submittedTargetCount": count,
    }
