from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from app.services.bid_type import BUSINESS_BID_TYPE


BUSINESS_S1_HANDOFF_SCHEMA_VERSION = "business-s1-handoff-v1"
PUBLISHED_S1_STATUS = "published"


def business_s1_handoff(project: dict[str, Any]) -> dict[str, Any]:
    stage_artifacts = project.get("stageArtifacts") if isinstance(project.get("stageArtifacts"), dict) else {}
    s1 = stage_artifacts.get("s1") if isinstance(stage_artifacts.get("s1"), dict) else {}
    if not s1:
        return {}
    bid_type = str(s1.get("bidType") or project.get("bidType") or "")
    parse_profile = str(s1.get("parseProfile") or "")
    if BUSINESS_BID_TYPE not in bid_type and parse_profile != "business":
        return {}
    return copy.deepcopy(s1)


def require_published_business_s1_handoff_if_present(project: dict[str, Any]) -> dict[str, Any]:
    handoff = business_s1_handoff(project)
    if not handoff:
        return {}
    status = str(handoff.get("status") or "")
    if status != PUBLISHED_S1_STATUS:
        raise ValueError(f"PWF S1 交接件尚未发布，当前状态为 {status or 'unknown'}，不能进入商务 S3/AI填写正式消费。")
    return handoff


def business_s1_consumption_context(project: dict[str, Any]) -> dict[str, Any]:
    handoff = require_published_business_s1_handoff_if_present(project)
    if not handoff:
        return {
            "source": "legacy_parse_result",
            "handoff": {},
            "paths": {},
            "structuredResultPath": "",
            "parseResult": copy.deepcopy(project.get("parse_result") if isinstance(project.get("parse_result"), dict) else {}),
        }

    paths = handoff.get("paths") if isinstance(handoff.get("paths"), dict) else {}
    structured_payload = _load_structured_payload_from_handoff(handoff, paths)
    parse_result = {
        "status": "completed",
        "parsedAt": str(handoff.get("publishedAt") or ""),
        "items": copy.deepcopy(structured_payload.get("items") if isinstance(structured_payload.get("items"), list) else []),
        "structured": copy.deepcopy(structured_payload.get("structured") if isinstance(structured_payload.get("structured"), dict) else {}),
        "summary": copy.deepcopy(handoff.get("summary") if isinstance(handoff.get("summary"), dict) else {}),
        "s1Handoff": compact_business_s1_handoff(handoff),
    }
    return {
        "source": "stageArtifacts.s1",
        "handoff": compact_business_s1_handoff(handoff),
        "paths": copy.deepcopy(paths),
        "structuredResultPath": str(paths.get("structuredResultPath") or ""),
        "parseResult": parse_result,
    }


def business_s1_parse_result(project: dict[str, Any]) -> dict[str, Any]:
    context = business_s1_consumption_context(project)
    parse_result = context.get("parseResult")
    return copy.deepcopy(parse_result if isinstance(parse_result, dict) else {})


def compact_business_s1_handoff(handoff: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("schemaVersion", "status", "version", "projectId", "bidType", "parseProfile", "publishedAt"):
        if key in handoff:
            result[key] = copy.deepcopy(handoff.get(key))
    paths = handoff.get("paths")
    if isinstance(paths, dict):
        result["paths"] = copy.deepcopy(paths)
    summary = handoff.get("summary")
    if isinstance(summary, dict):
        result["summary"] = copy.deepcopy(summary)
    return result


def _load_structured_payload_from_handoff(handoff: dict[str, Any], paths: dict[str, Any]) -> dict[str, Any]:
    structured_path = Path(str(paths.get("structuredResultPath") or "")).expanduser()
    if structured_path.exists() and structured_path.is_file():
        payload = json.loads(structured_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"PWF S1 结构化结果不是 JSON 对象：{structured_path}")
        return payload

    embedded_structured = handoff.get("structured")
    if isinstance(embedded_structured, dict):
        return {
            "schemaVersion": str(embedded_structured.get("schemaVersion") or ""),
            "items": copy.deepcopy(handoff.get("items") if isinstance(handoff.get("items"), list) else []),
            "structured": copy.deepcopy(embedded_structured),
        }

    raise ValueError(f"PWF S1 交接件缺少可读 structuredResultPath：{structured_path}")
