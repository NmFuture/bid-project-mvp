from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from docx import Document

from app.core.config import BASE_DIR, settings
from app.services.opencode_client import OpencodeClient


GAP_PLAN_SCHEMA_VERSION = "bid-tech-gap-plan-v1"
TABLE_FILL_SCHEMA_VERSION = "bid-tech-table-fill-v1"
GAP_PLANNER_SKILL_NAME = "bid-tech-gap-planner"
TABLE_FILL_SKILL_NAME = "bid-tech-table-filler"
GAP_PLANNER_RUNNER = BASE_DIR / "opencode" / "skill" / GAP_PLANNER_SKILL_NAME / "scripts" / "run_from_manifest.py"
TABLE_FILL_RUNNER = BASE_DIR / "opencode" / "skill" / TABLE_FILL_SKILL_NAME / "scripts" / "run_from_manifest.py"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_filename(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


def build_gap_plan_for_project(project: dict[str, Any]) -> dict[str, Any]:
    """Create a real plan from the confirmed directory and parse/material refs.

    The OpenCode skill owns the contract and is available in the image. The
    backend uses the same manifest and runner locally so tests and offline
    deployments do not depend on a live model just to materialize the JSON
    contract.
    """

    project_id = str(project.get("id") or "")
    project_dir = _project_dir(project)
    work_dir = project_dir / "s4_gap_workdir"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    toc_json_path = _resolve_toc_json(project, work_dir)
    parse_result_path = work_dir / "parse_result.json"
    parse_result_path.write_text(
        json.dumps(project.get("parse_result") or {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output_file = work_dir / "gap_plan.json"
    manifest_path = work_dir / "s4_gap_input.json"
    manifest = {
        "projectId": project_id,
        "projectName": str(project.get("name") or project_id),
        "bidType": str(project.get("bidType") or "技术标"),
        "workDir": str(work_dir),
        "tocJsonPath": str(toc_json_path),
        "parseResultPath": str(parse_result_path),
        "projectIdentity": project.get("identity") or {},
        "existingSubmissions": list((project.get("gap_state") or {}).get("submissions") or []),
        "outputFile": str(output_file),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    result = run_gap_planner_skill(manifest_path)
    plan_path = Path(str(result.get("outputFile") or output_file))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["planFile"] = str(plan_path)
    plan["manifestPath"] = str(manifest_path)
    plan["opencodeOutput"] = result.get("opencodeOutput") or {
        "status": "received",
        "sessionId": str(manifest_path),
        "providerId": "local-skill",
        "modelId": GAP_PLANNER_SKILL_NAME,
        "receivedAt": now_iso(),
        "parts": [{"type": "text", "text": json.dumps({"outputFile": str(plan_path)}, ensure_ascii=False)}],
    }
    return plan


def run_gap_planner_skill(manifest_path: Path) -> dict[str, Any]:
    return _run_local_skill_runner(GAP_PLANNER_RUNNER, manifest_path, GAP_PLAN_SCHEMA_VERSION)


def run_table_filler_skill(
    manifest_path: Path,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    prompt = _build_table_filler_prompt(manifest_path)
    try:
        result = OpencodeClient().run_bid_tech_table_filler_with_trace(
            prompt,
            stream_callback=(
                (lambda details: progress_callback("table_filler_delta", details))
                if progress_callback
                else None
            ),
        )
        return result
    except Exception:
        # Keep the feature usable in offline test/deploy environments. The
        # fallback executes the same skill runner and records local-skill trace.
        return _run_local_skill_runner(TABLE_FILL_RUNNER, manifest_path, TABLE_FILL_SCHEMA_VERSION)


def run_ai_fill_for_gap(
    project: dict[str, Any],
    gap_id: str,
    data: dict[str, Any],
    *,
    browser_base_url: str = "",
    onlyoffice_base_url: str = "",
) -> dict[str, Any]:
    gap_state = project.get("gap_state") or {}
    plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    item = next((entry for entry in items if str(entry.get("id") or "") == gap_id), None)
    if item is None:
        raise KeyError(gap_id)

    fill_tasks = item.get("fillTasks") if isinstance(item.get("fillTasks"), list) else []
    requested_task_id = str(data.get("fillTaskId") or "")
    task = next(
        (
            entry
            for entry in fill_tasks
            if not requested_task_id or str(entry.get("id") or "") == requested_task_id
        ),
        None,
    )
    if task is None:
        raise ValueError("当前缺口没有可执行的 AI 填写任务。")

    work_dir = _project_dir(project) / "s4_gap_workdir" / "ai_fill" / gap_id
    work_dir.mkdir(parents=True, exist_ok=True)
    artifact_id = f"ART-{gap_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    output_file = work_dir / f"{safe_filename(str(item.get('title') or gap_id), gap_id)}_AI填写.docx"
    manifest_path = work_dir / "table_fill_input.json"
    manifest = {
        "schemaVersion": TABLE_FILL_SCHEMA_VERSION,
        "projectId": str(project.get("id") or ""),
        "projectName": str(project.get("name") or ""),
        "gapId": gap_id,
        "fillTaskId": str(task.get("id") or ""),
        "title": str(item.get("title") or ""),
        "blankSource": task.get("blankSource") or {},
        "referenceMaterialIds": list(data.get("referenceMaterialIds") or []),
        "parseFieldIds": list(data.get("parseFieldIds") or []),
        "constraints": str(data.get("constraints") or ""),
        "operator": str(data.get("operator") or "当前用户"),
        "outputFile": str(output_file),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    result = run_table_filler_skill(manifest_path)
    resolved_output = Path(str(result.get("outputFile") or output_file))
    if not resolved_output.exists():
        raise RuntimeError(f"AI 填写未生成输出文件：{resolved_output}")

    artifact = {
        "id": artifact_id,
        "source": "ai_fill",
        "skill": TABLE_FILL_SKILL_NAME,
        "title": str(item.get("title") or resolved_output.stem),
        "fileName": resolved_output.name,
        "path": str(resolved_output),
        "createdAt": now_iso(),
        "operator": str(data.get("operator") or "当前用户"),
        "unfilledFields": list(result.get("unfilledFields") or []),
        "evidenceRefs": list(result.get("evidenceRefs") or []),
        "manifestPath": str(manifest_path),
        "opencodeOutput": result.get("opencodeOutput") or {},
        "onlyoffice": _artifact_onlyoffice_payload(
            project_id=str(project.get("id") or ""),
            artifact_id=artifact_id,
            file_name=resolved_output.name,
            browser_base_url=browser_base_url,
            onlyoffice_base_url=onlyoffice_base_url,
        ),
        "s7Ready": True,
    }

    task["status"] = "completed"
    task["outputArtifactId"] = artifact_id
    task["completedAt"] = artifact["createdAt"]
    item["status"] = "resolved"
    item.setdefault("resolvedArtifacts", []).append(artifact)
    item["resolvedAt"] = artifact["createdAt"]
    item["resolvedSource"] = artifact["fileName"]
    item["reviewNotes"] = list(item.get("reviewNotes") or [])
    if artifact["unfilledFields"]:
        item["reviewNotes"].append(f"AI 填写仍有未填字段：{len(artifact['unfilledFields'])} 项")

    plan["updatedAt"] = artifact["createdAt"]
    plan["summary"] = summarize_gap_plan(plan)
    gap_state["plan"] = plan
    gap_state["items"] = _legacy_items_from_plan(plan)
    gap_state["submittedForReview"] = False
    gap_state["reviewConfirmed"] = False
    gap_state["reviewedAt"] = ""
    return {"item": item, "artifact": artifact, "gapPlan": plan}


def register_manual_gap_upload(
    project: dict[str, Any],
    gap_id: str,
    data: dict[str, Any],
    *,
    browser_base_url: str = "",
    onlyoffice_base_url: str = "",
) -> dict[str, Any]:
    gap_state = project.get("gap_state") or {}
    plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    item = next((entry for entry in items if str(entry.get("id") or "") == gap_id), None)
    if item is None:
        raise KeyError(gap_id)
    files = [entry for entry in data.get("files") or [] if isinstance(entry, dict)]
    if not files:
        raise ValueError("至少需要提交一个文件。")

    work_dir = _project_dir(project) / "s4_gap_workdir" / "manual_upload" / gap_id
    work_dir.mkdir(parents=True, exist_ok=True)
    created_at = now_iso()
    artifacts: list[dict[str, Any]] = []
    for index, file in enumerate(files, start=1):
        name = safe_filename(str(file.get("name") or f"{gap_id}-{index}.docx"), f"{gap_id}-{index}.docx")
        if not name.lower().endswith(".docx"):
            name = f"{Path(name).stem}.docx"
        output_file = work_dir / name
        content = str(file.get("data") or file.get("text") or file.get("content") or "")
        _write_manual_upload_docx(output_file, title=str(item.get("title") or name), content=content)
        artifact_id = f"ART-{gap_id}-UPLOAD-{index}"
        artifacts.append(
            {
                "id": artifact_id,
                "source": "manual_upload",
                "skill": "",
                "title": str(item.get("title") or output_file.stem),
                "fileName": output_file.name,
                "path": str(output_file),
                "createdAt": created_at,
                "operator": str(data.get("operator") or "当前用户"),
                "unfilledFields": [],
                "evidenceRefs": [],
                "onlyoffice": _artifact_onlyoffice_payload(
                    project_id=str(project.get("id") or ""),
                    artifact_id=artifact_id,
                    file_name=output_file.name,
                    browser_base_url=browser_base_url,
                    onlyoffice_base_url=onlyoffice_base_url,
                ),
                "s7Ready": True,
            }
        )

    item["status"] = "resolved"
    item.setdefault("resolvedArtifacts", []).extend(artifacts)
    item["resolvedAt"] = created_at
    item["resolvedSource"] = artifacts[0]["fileName"]
    item["latestUploadAt"] = created_at
    item["latestSubmissionId"] = artifacts[0]["id"]
    plan["updatedAt"] = created_at
    plan["summary"] = summarize_gap_plan(plan)
    gap_state["plan"] = plan
    gap_state["items"] = _legacy_items_from_plan(plan)
    gap_state["submittedForReview"] = False
    gap_state["reviewConfirmed"] = False
    gap_state["reviewedAt"] = ""
    return {"item": item, "artifact": artifacts[0], "artifacts": artifacts, "gapPlan": plan}


def _write_manual_upload_docx(path: Path, *, title: str, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    doc.add_heading(title or path.stem, level=1)
    text = content.strip() or "人工上传客户资料，原始文件内容请以项目素材库归档为准。"
    for paragraph in text.splitlines() or [text]:
        doc.add_paragraph(paragraph)
    doc.save(path)


def summarize_gap_plan(plan: dict[str, Any]) -> dict[str, Any]:
    items = [item for item in plan.get("items") or [] if isinstance(item, dict)]
    return {
        "totalTocItems": len(items),
        "matchedCount": sum(1 for item in items if item.get("status") == "matched"),
        "missingCount": sum(1 for item in items if item.get("status") in {"missing", "needs_input"}),
        "resolvedCount": sum(1 for item in items if item.get("status") == "resolved"),
        "ignoredCount": sum(1 for item in items if item.get("status") == "ignored"),
        "structuralCount": sum(1 for item in items if item.get("status") == "structural"),
        "fillableTaskCount": sum(len(item.get("fillTasks") or []) for item in items),
        "blockingCount": sum(1 for item in items if item.get("status") in {"missing", "needs_input", "filling"}),
    }


def check_gap_integrity(plan: dict[str, Any]) -> dict[str, Any]:
    summary = summarize_gap_plan(plan)
    blocking_items = [
        {
            "id": str(item.get("id") or ""),
            "number": str(item.get("number") or ""),
            "title": str(item.get("title") or ""),
            "status": str(item.get("status") or ""),
        }
        for item in plan.get("items") or []
        if str(item.get("status") or "") in {"missing", "needs_input", "filling"}
    ]
    return {
        "status": "passed" if not blocking_items else "blocked",
        "checkedAt": now_iso(),
        "blockingCount": len(blocking_items),
        "blockingItems": blocking_items,
        "summary": summary,
    }


def _project_dir(project: dict[str, Any]) -> Path:
    parse_storage = project.get("parse_storage") or {}
    raw_project_dir = str(parse_storage.get("projectDir") or "").strip()
    project_id = str(project.get("id") or "")
    project_dir = Path(raw_project_dir).expanduser() if raw_project_dir else settings.parsed_dir / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def _resolve_toc_json(project: dict[str, Any], work_dir: Path) -> Path:
    project_id = str(project.get("id") or "")
    parse_storage = project.get("parse_storage") or {}
    candidates = []
    raw_project_dir = str(parse_storage.get("projectDir") or "").strip()
    if raw_project_dir:
        candidates.append(Path(raw_project_dir) / "s2_toc_workdir" / "投标文件-总目录.json")
    directory_output = ((project.get("directory_state") or {}).get("opencodeOutput") or {})
    for value in (directory_output.get("tocJsonPath"), directory_output.get("outputFile")):
        if value:
            candidates.append(Path(str(value)))
    for candidate in candidates:
        if candidate.exists() and candidate.suffix.lower() == ".json":
            target = work_dir / "投标文件-总目录.json"
            shutil.copy2(candidate, target)
            return target

    outline_nodes = list((project.get("outline_state") or {}).get("nodes") or [])
    output = {
        "schema_version": "bid-toc-json-v1",
        "document_title": f"{project.get('name') or project_id}投标文件总目录",
        "project": {
            "owner": project.get("customerName") or "",
            "name": project.get("name") or project_id,
            "code": project.get("projectCode") or project_id,
        },
        "items": _outline_nodes_to_toc_items(outline_nodes),
    }
    target = work_dir / "投标文件-总目录.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _outline_nodes_to_toc_items(nodes: list[dict[str, Any]], prefix: str = "", level: int = 1) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, node in enumerate(nodes, start=1):
        number = f"{prefix}.{index}" if prefix else str(index)
        items.append(
            {
                "order": len(items) + 1,
                "number": number,
                "title": str(node.get("title") or "").strip(),
                "level": level,
                "annotation": str(node.get("annotation") or "保留"),
                "source": "outline_state",
                "reason": "",
                "material_refs": list(node.get("material_refs") or []),
            }
        )
        children = node.get("children") or []
        if isinstance(children, list):
            child_items = _outline_nodes_to_toc_items(children, number, level + 1)
            for child in child_items:
                child["order"] = len(items) + 1
                items.append(child)
    return items


def _run_local_skill_runner(runner: Path, manifest_path: Path, schema_version: str) -> dict[str, Any]:
    if not runner.exists():
        raise RuntimeError(f"Skill runner 不存在：{runner}")
    result = subprocess.run(
        [sys.executable, str(runner), "--manifest", str(manifest_path), "--response", "summary"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        detail = "\n".join(part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part)
        raise RuntimeError(f"Skill runner 执行失败（{result.returncode}）：{detail}")
    payload = json.loads(result.stdout or "{}")
    payload.setdefault("schema_version", schema_version)
    payload.setdefault(
        "opencodeOutput",
        {
            "status": "received",
            "sessionId": str(manifest_path),
            "providerId": "local-skill",
            "modelId": runner.parent.parent.name,
            "receivedAt": now_iso(),
            "parts": [{"type": "text", "text": result.stdout.strip()}],
        },
    )
    return payload


def _build_table_filler_prompt(manifest_path: Path) -> str:
    return f"""
Use the {TABLE_FILL_SKILL_NAME} skill.

你现在在做技术标缺口项 AI 填写。后端已经准备好 manifest，其中包含待填写空表/Word、人工指定的参考素材、解析字段和输出路径。

manifest：{manifest_path}

请直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 1800000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径：

s4fill {manifest_path}

只返回命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
""".strip()


def _artifact_onlyoffice_payload(
    *,
    project_id: str,
    artifact_id: str,
    file_name: str,
    browser_base_url: str = "",
    onlyoffice_base_url: str = "",
) -> dict[str, Any]:
    file_url = f"/api/projects/{project_id}/gaps/artifacts/{artifact_id}/content/{file_name}"
    browser_url = f"{browser_base_url}{file_url}" if browser_base_url else file_url
    document_server_url = f"{onlyoffice_base_url}{file_url}" if onlyoffice_base_url else file_url
    return {
        "status": "ready",
        "mode": "view",
        "fileUrl": browser_url,
        "documentServerFileUrl": document_server_url,
        "documentKey": f"{project_id}-{artifact_id}",
        "title": file_name,
    }


def _legacy_items_from_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, item in enumerate(plan.get("items") or [], start=1):
        status = str(item.get("status") or "")
        if status in {"matched", "structural"}:
            continue
        items.append(
            {
                "id": str(item.get("id") or f"GAP-{index}"),
                "section": str(item.get("section") or item.get("parentTitle") or ""),
                "title": str(item.get("title") or ""),
                "desc": str(item.get("gapReason") or item.get("reason") or "请补充该目录项所需素材。"),
                "priority": str(item.get("priority") or "medium"),
                "bidType": "技术标",
                "status": "resolved" if status == "resolved" else "skipped" if status == "ignored" else "pending",
                "skipReason": str(item.get("skipReason") or ""),
                "resolvedSource": str(item.get("resolvedSource") or ""),
                "resolvedAt": str(item.get("resolvedAt") or ""),
                "latestUploadAt": str(item.get("latestUploadAt") or ""),
                "latestSubmissionId": str(item.get("latestSubmissionId") or ""),
            }
        )
    return items
