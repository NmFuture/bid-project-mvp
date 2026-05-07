from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

from app.core.config import settings


def workspace_slug_for_bid_type(bid_type: Any = "技术标") -> str:
    return "business" if str(bid_type or "").strip() == "商务标" else "technical"


def workspace_dir(project_id: str, bid_type: Any = "技术标") -> Path:
    return settings.documents_dir / project_id / f"{workspace_slug_for_bid_type(bid_type)}-workspace"


def technical_workspace_dir(project_id: str) -> Path:
    return workspace_dir(project_id, "技术标")


def business_workspace_dir(project_id: str) -> Path:
    return workspace_dir(project_id, "商务标")


def workspace_appendices_dir(project_id: str, bid_type: Any = "技术标") -> Path:
    return workspace_dir(project_id, bid_type) / "appendices"


def workspace_parse_dir(project_id: str, bid_type: Any = "技术标") -> Path:
    return workspace_dir(project_id, bid_type) / "parse"


def workspace_stage_dir(project_id: str, stage_name: str, bid_type: Any = "技术标") -> Path:
    return workspace_dir(project_id, bid_type) / stage_name


def technical_workspace_appendices_dir(project_id: str) -> Path:
    return workspace_appendices_dir(project_id, "技术标")


def technical_workspace_parse_dir(project_id: str) -> Path:
    return workspace_parse_dir(project_id, "技术标")


def technical_workspace_stage_dir(project_id: str, stage_name: str) -> Path:
    return workspace_stage_dir(project_id, stage_name, "技术标")


def legacy_workspace_roots(project_id: str, parse_storage: dict[str, Any] | None = None) -> list[Path]:
    roots: list[Path] = []
    raw_project_dir = str((parse_storage or {}).get("projectDir") or "").strip()
    if raw_project_dir:
        roots.append(Path(raw_project_dir).expanduser())
    roots.append(technical_workspace_dir(project_id))
    roots.append(settings.parsed_dir / project_id)
    roots.append(technical_workspace_parse_dir(project_id))

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def parse_temp_workspace_dir(project_id: str) -> Path:
    return settings.parsed_dir / project_id


def cleanup_parse_temp_workspace(project_id: str) -> bool:
    path = parse_temp_workspace_dir(project_id)
    if not path.exists():
        return False

    root = settings.parsed_dir.resolve()
    target = path.resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError(f"Refusing to remove parse workspace outside parsed_dir: {target}")
    if target == root:
        raise ValueError("Refusing to remove parsed_dir root.")

    shutil.rmtree(target)
    return True


def _copy_file_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists() or not source.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    return True


def _workspace_appendix_item(
    project_id: str,
    appendix: dict[str, Any],
    destination: Path,
    workspace_slug: str = "technical",
) -> dict[str, Any]:
    item = copy.deepcopy(appendix)
    workspace_path = f"{workspace_slug}-workspace/appendices/{destination.name}"
    item["docxPath"] = str(destination)
    item["workspacePath"] = workspace_path
    return item


def _load_json_if_exists(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _copy_parse_documents(parse_storage: dict[str, Any], parse_dir: Path) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for document in parse_storage.get("documents", []) if isinstance(parse_storage.get("documents"), list) else []:
        if not isinstance(document, dict):
            continue
        item = copy.deepcopy(document)
        text_path = Path(str(item.get("textPath") or ""))
        if text_path.exists() and text_path.is_file():
            destination = parse_dir / text_path.name
            if _copy_file_if_exists(text_path, destination):
                item["textPath"] = str(destination)
        documents.append(item)
    return documents


def _remove_stale_appendix_files(appendix_dir: Path, desired_names: set[str]) -> None:
    if not appendix_dir.exists():
        return
    for child in appendix_dir.iterdir():
        if child.name in desired_names:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)


def promote_parse_artifacts_to_workspace(
    project_id: str,
    parse_result: dict[str, Any],
    parse_storage: dict[str, Any],
    *,
    bid_type: Any = "技术标",
    clean_workspace: bool = True,
) -> dict[str, Any]:
    """Copy the current S1 parse JSON and generated appendix Word files into the project workspace."""

    workspace_slug = workspace_slug_for_bid_type(bid_type)
    workspace_root = workspace_dir(project_id, bid_type)
    parse_dir = workspace_parse_dir(project_id, bid_type)
    appendix_dir = workspace_appendices_dir(project_id, bid_type)
    parse_dir.mkdir(parents=True, exist_ok=True)
    appendix_dir.mkdir(parents=True, exist_ok=True)

    copied_parse_files: list[str] = []
    combined_text_path = parse_dir / "combined.txt"
    if _copy_file_if_exists(Path(str(parse_storage.get("combinedTextPath") or "")), combined_text_path):
        copied_parse_files.append(str(combined_text_path))

    workspace_documents = _copy_parse_documents(parse_storage, parse_dir)

    workspace_result = copy.deepcopy(parse_result)
    structured = workspace_result.get("structured")
    appendices = structured.get("appendices") if isinstance(structured, dict) else []
    promoted_appendices: list[dict[str, Any]] = []
    appendix_sources: list[tuple[dict[str, Any], Path, Path]] = []
    for appendix in appendices if isinstance(appendices, list) else []:
        if not isinstance(appendix, dict):
            continue
        source = Path(str(appendix.get("docxPath") or ""))
        if not source.exists() or not source.is_file():
            continue
        destination = appendix_dir / source.name
        appendix_sources.append((appendix, source, destination))

    if clean_workspace:
        _remove_stale_appendix_files(appendix_dir, {destination.name for _, _, destination in appendix_sources})

    for appendix, source, destination in appendix_sources:
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        promoted_appendices.append(_workspace_appendix_item(project_id, appendix, destination, workspace_slug))

    if isinstance(structured, dict):
        structured["appendices"] = promoted_appendices
        structured["workspaceArtifacts"] = {
            "root": str(workspace_root),
            "parseDir": str(parse_dir),
            "appendicesDir": str(appendix_dir),
            "parseFiles": copied_parse_files,
            "appendixCount": len(promoted_appendices),
        }

    structured_result_path = parse_dir / "s1_structured_result.json"
    structured_payload = _load_json_if_exists(str(parse_storage.get("structuredResultPath") or ""))
    structured_payload["items"] = copy.deepcopy(workspace_result.get("items") or structured_payload.get("items") or [])
    structured_payload["structured"] = copy.deepcopy(workspace_result.get("structured") or {})
    structured_payload.setdefault("schemaVersion", "bid-tender-structured-v1")
    structured_result_path.write_text(json.dumps(structured_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    copied_parse_files.append(str(structured_result_path))

    skill_manifest_path = parse_dir / "s1_parse_manifest.json"
    skill_manifest = _load_json_if_exists(str(parse_storage.get("skillManifestPath") or ""))
    skill_manifest.update(
        {
            "projectId": project_id,
            "combinedTextPath": str(combined_text_path),
            "structuredResultPath": str(structured_result_path),
            "documents": workspace_documents,
        }
    )
    skill_manifest_path.write_text(json.dumps(skill_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    copied_parse_files.append(str(skill_manifest_path))

    manifest_path = parse_dir / "manifest.json"
    manifest = _load_json_if_exists(str(parse_storage.get("manifestPath") or ""))
    manifest.update(
        {
            "projectId": project_id,
            "combinedTextPath": str(combined_text_path),
            "documents": workspace_documents,
            "structuredResultPath": str(structured_result_path),
            "skillManifestPath": str(skill_manifest_path),
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    copied_parse_files.append(str(manifest_path))

    (parse_dir / "parse-result.workspace.json").write_text(
        json.dumps(workspace_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    copied_parse_files.append(str(parse_dir / "parse-result.workspace.json"))

    workspace_storage = copy.deepcopy(parse_storage)
    workspace_storage.update(
        {
            "projectDir": str(workspace_root),
            "parseDir": str(parse_dir),
            "combinedTextPath": str(combined_text_path),
            "manifestPath": str(manifest_path),
            "structuredResultPath": str(structured_result_path),
            "skillManifestPath": str(skill_manifest_path),
            "documents": workspace_documents,
            "items": copy.deepcopy(workspace_result.get("items") or parse_storage.get("items") or []),
            "structured": copy.deepcopy(workspace_result.get("structured") or parse_storage.get("structured") or {}),
        }
    )

    return {
        "parseResult": workspace_result,
        "parseStorage": workspace_storage,
        "artifacts": {
            "root": str(workspace_root),
            "parseDir": str(parse_dir),
            "appendicesDir": str(appendix_dir),
            "parseFiles": copied_parse_files,
            "appendixCount": len(promoted_appendices),
        },
    }
