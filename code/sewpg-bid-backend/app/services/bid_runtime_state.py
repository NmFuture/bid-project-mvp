from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.bid_type import require_bid_type
from app.services.workspace_artifacts import business_workspace_dir, workspace_parse_dir


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_outline_nodes(project_name: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "OL-1",
            "title": "项目概况",
            "children": [
                {"id": "OL-1-1", "title": "项目背景", "children": []},
                {"id": "OL-1-2", "title": "建设目标", "children": []},
            ],
        },
        {
            "id": "OL-2",
            "title": "技术方案",
            "children": [
                {"id": "OL-2-1", "title": f"{project_name}总体方案", "children": []},
            ],
        },
        {
            "id": "OL-3",
            "title": "实施与保障",
            "children": [],
        },
    ]


def build_directory_event(
    message: str,
    *,
    level: str = "info",
    step: str = "general",
    at: str | None = None,
) -> dict[str, Any]:
    return {
        "at": at or now_iso(),
        "level": level,
        "step": step,
        "message": message,
    }


def build_directory_opencode_output(
    *,
    status: str = "idle",
    session_id: str = "",
    provider_id: str = "",
    model_id: str = "",
    received_at: str = "",
    parts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "sessionId": session_id,
        "providerId": provider_id,
        "modelId": model_id,
        "receivedAt": received_at,
        "parts": copy.deepcopy(parts or []),
    }


def build_parse_event(
    message: str,
    *,
    level: str = "info",
    step: str = "general",
    at: str | None = None,
) -> dict[str, Any]:
    return {
        "at": at or now_iso(),
        "level": level,
        "step": step,
        "message": message,
    }


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        if not path.exists() or not path.is_file():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def empty_parse_result(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "idle",
        "parsedAt": "",
        "project": {
            "id": str(project.get("id") or ""),
            "files": copy.deepcopy(project.get("files") or []),
            "templateFiles": copy.deepcopy(project.get("templateFiles") or []),
            "startDate": str(project.get("startDate") or ""),
            "endDate": str(project.get("endDate") or project.get("deadline") or ""),
            "deadline": str(project.get("deadline") or project.get("endDate") or ""),
            "currentStage": project.get("currentStage") or 1,
        },
        "sourceFiles": [],
        "items": [],
        "structured": {},
        "summary": {
            "fileCount": 0,
            "extractedCount": 0,
            "textLength": 0,
            "textPreview": "",
            "warnings": [],
        },
    }


def recover_parse_result(project: dict[str, Any]) -> dict[str, Any]:
    project_id = str(project.get("id") or "")
    bid_type = require_bid_type(
        project.get("bidType"),
        error_message="解析结果恢复必须显式传入技术标或商务标项目。",
    )
    parse_dir = workspace_parse_dir(project_id, bid_type)
    candidates = [
        parse_dir / "parse-result.workspace.json",
        parse_dir / "s1_structured_result.json",
        business_workspace_dir(project_id) / "parse" / "parse-result.workspace.json",
        settings.documents_dir / project_id / "technical-workspace" / "parse" / "parse-result.workspace.json",
        settings.parsed_dir / project_id / "parse-result.workspace.json",
        settings.parsed_dir / project_id / "s1_structured_result.json",
    ]
    for path in candidates:
        payload = read_json_file(path)
        if not payload:
            continue
        if path.name == "s1_structured_result.json":
            payload = {
                "status": "completed",
                "parsedAt": now_iso(),
                "sourceFiles": [],
                "items": copy.deepcopy(payload.get("items") or []),
                "structured": copy.deepcopy(payload.get("structured") or {}),
                "summary": payload.get("summary") if isinstance(payload.get("summary"), dict) else {},
            }
        payload.setdefault("status", "completed")
        payload.setdefault("parsedAt", now_iso())
        payload.setdefault("sourceFiles", [])
        payload.setdefault("items", [])
        payload.setdefault("structured", {})
        payload.setdefault(
            "summary",
            {
                "fileCount": len(payload.get("sourceFiles") or []),
                "extractedCount": len(payload.get("items") or []),
                "textLength": 0,
                "textPreview": "",
                "warnings": ["解析结果由项目工作区自动恢复。"],
            },
        )
        return payload
    return empty_parse_result(project)


def recover_parse_storage(project: dict[str, Any]) -> dict[str, Any]:
    project_id = str(project.get("id") or "")
    bid_type = require_bid_type(
        project.get("bidType"),
        error_message="解析存储恢复必须显式传入技术标或商务标项目。",
    )
    parse_dir = workspace_parse_dir(project_id, bid_type)
    manifest = read_json_file(parse_dir / "manifest.json")
    structured_path = parse_dir / "s1_structured_result.json"
    return {
        "projectDir": str(parse_dir.parent) if parse_dir.exists() else "",
        "parseDir": str(parse_dir) if parse_dir.exists() else "",
        "combinedTextPath": str(parse_dir / "combined.txt") if (parse_dir / "combined.txt").exists() else "",
        "manifestPath": str(parse_dir / "manifest.json") if (parse_dir / "manifest.json").exists() else "",
        "structuredResultPath": str(structured_path) if structured_path.exists() else "",
        "skillManifestPath": str(parse_dir / "s1_parse_manifest.json") if (parse_dir / "s1_parse_manifest.json").exists() else "",
        "documents": list(manifest.get("documents") or []) if isinstance(manifest.get("documents"), list) else [],
    }


def recover_directory_state(project: dict[str, Any]) -> dict[str, Any]:
    project_id = str(project.get("id") or "")
    toc_path = recover_business_toc_path(project)
    generated_at = now_iso()
    if toc_path:
        return {
            "status": "completed",
            "percentage": 100,
            "summary": "已从商务标 S2 目录产物恢复目录状态。",
            "generatedAt": generated_at,
            "output": {
                "fileName": f"{str(project.get('name') or project_id)}_目录.docx",
                "fileType": "docx",
                "chapterCount": 0,
            },
            "opencodeOutput": {
                **build_directory_opencode_output(),
                "tocJsonPath": str(toc_path),
                "outputFile": str(toc_path),
            },
            "ruleEvidence": {},
            "events": [
                build_directory_event(
                    "已从商务标 S2 目录产物恢复目录状态。",
                    level="info",
                    step="recovered",
                    at=generated_at,
                )
            ],
            "tasks": [
                {"id": "task-1", "label": "准备目录候选", "status": "done"},
                {"id": "task-2", "label": "futurecode 语义审核", "status": "done"},
                {"id": "task-3", "label": "保存审核目录", "status": "done"},
            ],
        }
    return default_directory_state()


def default_directory_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "percentage": 0,
        "summary": "尚未生成目录。",
        "generatedAt": "",
        "output": None,
        "opencodeOutput": build_directory_opencode_output(),
        "ruleEvidence": {},
        "events": [],
        "tasks": [
            {"id": "task-1", "label": "准备目录候选", "status": "pending"},
            {"id": "task-2", "label": "futurecode 语义审核", "status": "pending"},
            {"id": "task-3", "label": "保存审核目录", "status": "pending"},
        ],
    }


def recover_outline_state(project: dict[str, Any]) -> dict[str, Any]:
    toc_path = recover_business_toc_path(project)
    nodes: list[dict[str, Any]] = []
    generated_at = now_iso()
    if toc_path:
        toc = read_json_file(toc_path)
        items = toc.get("items") if isinstance(toc, dict) else []
        if isinstance(items, list):
            nodes = outline_nodes_from_toc_items(items)
        generated_at = str(toc.get("generatedAt") or toc.get("generated_at") or generated_at) if isinstance(toc, dict) else generated_at
    return {
        "outlineVersion": 1,
        "reviewStatus": "confirmed" if nodes else "draft",
        "generatedAt": generated_at if nodes else "",
        "summary": {"totalNodeCount": count_outline_nodes(nodes)},
        "nodes": copy.deepcopy(nodes),
        "recoveredFrom": str(toc_path or ""),
    }


def ensure_project_runtime_states(project: dict[str, Any]) -> dict[str, Any]:
    from app.services.bid_fill_state import default_fill_state, default_fill_tasks
    from app.services.bid_parse_state import default_parse_progress
    from app.services.bid_project_state import default_document_state

    require_bid_type(
        project.get("bidType"),
        error_message="项目运行态必须显式传入技术标或商务标。",
    )
    if not isinstance(project.get("parse_result"), dict):
        project["parse_result"] = recover_parse_result(project)
    if not isinstance(project.get("parse_storage"), dict):
        project["parse_storage"] = recover_parse_storage(project)
    if not isinstance(project.get("parse_progress"), dict):
        status = str((project.get("parse_result") or {}).get("status") or "idle")
        project["parse_progress"] = default_parse_progress()
        if status == "completed":
            project["parse_progress"].update(
                {
                    "status": "completed",
                    "percentage": 100,
                    "summary": "已从项目工作区恢复解析结果。",
                    "completedAt": str((project.get("parse_result") or {}).get("parsedAt") or ""),
                }
            )
    if not isinstance(project.get("fill_state"), dict):
        project["fill_state"] = default_fill_state(project)
    if not isinstance(project.get("directory_state"), dict):
        project["directory_state"] = recover_directory_state(project)
    if not isinstance(project.get("outline_state"), dict):
        project["outline_state"] = recover_outline_state(project)
    if not isinstance(project.get("document_state"), dict):
        project["document_state"] = default_document_state(
            str(project["id"]),
            str(project.get("name") or project["id"]),
        )
    project["fill_state"].setdefault("opencodeOutput", build_directory_opencode_output())
    project["fill_state"].setdefault("events", [])
    project["fill_state"].setdefault("tasks", default_fill_tasks(project))
    return project


def recover_business_toc_path(project: dict[str, Any]) -> Path | None:
    project_id = str(project.get("id") or "")
    if not project_id:
        return None
    candidates: list[Path] = []
    directory_state = project.get("directory_state") if isinstance(project.get("directory_state"), dict) else {}
    opencode_output = directory_state.get("opencodeOutput") if isinstance(directory_state.get("opencodeOutput"), dict) else {}
    for value in (opencode_output.get("tocJsonPath"), opencode_output.get("outputFile")):
        if value:
            candidates.append(Path(str(value)).expanduser())
    candidates.extend(
        [
            settings.documents_dir / project_id / "business-workspace" / "s2_toc_workdir" / settings.s2_toc_output_file_name,
            settings.documents_dir / project_id / "business-workspace" / "s2_toc_workdir" / "toc.json",
            settings.documents_dir / project_id / "business-workspace" / "gaps" / settings.s2_toc_output_file_name,
            settings.documents_dir / project_id / "business-workspace" / "gaps" / "toc.json",
        ]
    )
    for candidate in candidates:
        if candidate.exists() and candidate.is_file() and candidate.suffix.lower() == ".json":
            return candidate
    return None


def outline_nodes_from_directory_toc(project: dict[str, Any]) -> list[dict[str, Any]]:
    toc_path = recover_business_toc_path(project)
    if not toc_path:
        return []
    toc = read_json_file(toc_path)
    items = toc.get("items") if isinstance(toc, dict) else None
    if not isinstance(items, list):
        return []
    return outline_nodes_from_toc_items(items)


def outline_nodes_from_toc_items(items: list[Any]) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []
    counters: list[int] = []
    for fallback_order, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        try:
            level = max(1, int(item.get("level") or 1))
        except (TypeError, ValueError):
            level = 1
        if not stack and level > 1:
            level = 1
        elif stack and level > stack[-1][0] + 1:
            level = stack[-1][0] + 1
        while stack and stack[-1][0] >= level:
            stack.pop()
        counters = counters[:level]
        if len(counters) < level:
            counters.extend([0] * (level - len(counters)))
        counters[level - 1] += 1
        title = str(item.get("title") or item.get("name") or f"未命名章节{fallback_order}").strip()
        node = {
            "id": "OL-" + "-".join(str(part) for part in counters[:level] if part),
            "title": title,
            "children": [],
            "tocNumber": str(item.get("number") or "").strip(),
            "annotation": str(item.get("annotation") or "").strip(),
            "required_status": str(item.get("required_status") or item.get("requiredStatus") or "").strip(),
            "requiredStatus": str(item.get("requiredStatus") or item.get("required_status") or "").strip(),
            "source_text": str(item.get("source_text") or item.get("sourceText") or "").strip(),
            "sourceText": str(item.get("sourceText") or item.get("source_text") or "").strip(),
            "source": str(item.get("source") or "").strip(),
            "reason": str(item.get("reason") or "").strip(),
        }
        if isinstance(item.get("source_refs"), list):
            node["sourceRefs"] = copy.deepcopy(item["source_refs"])
        if isinstance(item.get("material_refs"), list):
            node["materialRefs"] = copy.deepcopy(item["material_refs"])
        if stack:
            stack[-1][1].setdefault("children", []).append(node)
        else:
            roots.append(node)
        stack.append((level, node))
    return roots


def count_outline_nodes(nodes: list[dict[str, Any]]) -> int:
    total = 0
    for node in nodes:
        total += 1
        total += count_outline_nodes(node.get("children") or [])
    return total
