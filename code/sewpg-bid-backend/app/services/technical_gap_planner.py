from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR, settings
from app.services.bid_type import TECHNICAL_BID_TYPE, require_bid_type
from app.services.identity import build_project_material_scope
from app.services.opencode_client import OpencodeClient
from app.services.technical_gap_domain import summarize_technical_gap_plan
from app.services.technical_material_store import technical_material_store
from app.services.turbine_models import project_turbine_model
from app.services.workspace_artifacts import legacy_workspace_roots, technical_workspace_dir, technical_workspace_stage_dir


TECHNICAL_GAP_PLAN_SCHEMA_VERSION = "bid-tech-gap-plan-v1"
TECHNICAL_GAP_PLANNER_SKILL_NAME = "bid-tech-gap-planner"
TECHNICAL_TABLE_FILL_SKILL_NAME = "bid-tech-table-filler"
TECHNICAL_WORD_FILL_SKILL_NAME = "bid-tech-word-placeholder-filler"
GAP_PLANNER_RUNNER = BASE_DIR / "opencode" / "skills" / TECHNICAL_GAP_PLANNER_SKILL_NAME / "scripts" / "run_from_manifest.py"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _object_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _safe_filename(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


def _project_dir(project: dict[str, Any]) -> Path:
    project_id = str(project.get("id") or "")
    project_dir = technical_workspace_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def _run_async(awaitable: Any) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    loop_thread_id = getattr(loop, "_thread_id", None)
    if loop_thread_id is not None and threading.get_ident() == loop_thread_id:
        raise RuntimeError(
            "_run_async was called from the running event loop's own thread. "
            "Wrap the calling sync code with asyncio.to_thread or run it in a worker thread."
        )

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(awaitable)
        except BaseException as exc:  # pragma: no cover - re-raised in caller
            error["value"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error["value"]
    return result.get("value")


def _allowed_technical_material_index(material_scope: dict[str, Any], turbine_model: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scope in material_scope.get("readableScopes") or []:
        if not isinstance(scope, dict):
            continue
        folder_path = str(scope.get("path") or "").strip()
        if not folder_path:
            continue
        payload = _run_async(
            technical_material_store.raw_files(
                folder_path=folder_path,
                material_tier=str(scope.get("materialTier") or ""),
                turbine_model=turbine_model,
                recursive=True,
                page=1,
                page_size=1000,
            )
        )
        for raw in payload.get("items") or []:
            if not isinstance(raw, dict):
                continue
            material_id = str(raw.get("id") or "")
            if not material_id or material_id in seen:
                continue
            seen.add(material_id)
            items.append(
                {
                    "id": material_id,
                    "name": str(raw.get("name") or ""),
                    "folderPath": str(raw.get("folderPath") or ""),
                    "materialTier": str(raw.get("materialTier") or scope.get("materialTier") or ""),
                    "hasCleanedWord": bool(raw.get("hasCleanedWord")),
                    "cleanedFileName": str(raw.get("cleanedFileName") or ""),
                    "cleanStatus": str(raw.get("cleanStatus") or ""),
                    "turbineModelLabel": str(raw.get("turbineModelLabel") or ""),
                    "updatedAt": str(raw.get("updatedAt") or ""),
                }
            )
    return items


def _is_material_word_fill_task(item: dict[str, Any], task: dict[str, Any]) -> bool:
    blank = task.get("blankSource") if isinstance(task.get("blankSource"), dict) else {}
    source_type = str(blank.get("sourceType") or "")
    usage = str(item.get("usage") or "")
    try:
        placeholder_count = int(blank.get("placeholderCount") or 0)
    except (TypeError, ValueError):
        placeholder_count = 0
    material_id = str(blank.get("materialId") or blank.get("id") or "")
    return (
        source_type == "material_fill_template"
        or (
            usage in {"section_fill", "chapter_fill"}
            and placeholder_count > 0
            and material_id.startswith("RAW-")
        )
    )


def normalize_technical_gap_plan_fill_task_skills(plan: dict[str, Any]) -> int:
    repaired = 0
    for item in _object_items(plan.get("items")):
        for task in _object_items(item.get("fillTasks")):
            current = str(task.get("skill") or "")
            expected = TECHNICAL_WORD_FILL_SKILL_NAME if _is_material_word_fill_task(item, task) else ""
            if not expected or current == expected:
                continue
            task["skill"] = expected
            repaired += 1
    if repaired:
        plan["summary"] = summarize_technical_gap_plan(plan)
    return repaired


def _validate_technical_gap_plan_toc_coverage(plan: dict[str, Any], toc_json_path: Path) -> None:
    try:
        toc = json.loads(toc_json_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - malformed workspace input
        raise RuntimeError(f"缺口识别无法读取审核目录：{toc_json_path}") from exc
    toc_items = _object_items(toc.get("items"))
    plan_items = _object_items(plan.get("items"))
    expected_count = len(toc_items)
    actual_count = len(plan_items)
    summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
    summary_count = int(summary.get("totalTocItems") or 0)
    if expected_count == actual_count and (summary_count in (0, expected_count)):
        return
    raise RuntimeError(
        "缺口识别结果不完整："
        f"S2 审核目录有 {expected_count} 个目录项，"
        f"Skill 输出 {actual_count} 个目录项，"
        f"summary.totalTocItems={summary_count}。请重新运行 bid-tech-gap-planner。"
    )


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


def _resolve_toc_json(project: dict[str, Any], work_dir: Path) -> Path:
    project_id = str(project.get("id") or "")
    parse_storage = project.get("parse_storage") or {}
    candidates = []
    directory_output = ((project.get("directory_state") or {}).get("opencodeOutput") or {})
    for value in (directory_output.get("tocJsonPath"), directory_output.get("outputFile")):
        if value:
            candidates.append(Path(str(value)))
    for root in legacy_workspace_roots(project_id, parse_storage):
        s2_work_dir = root / "s2_toc_workdir"
        candidates.extend(path for path in sorted(s2_work_dir.glob("*.json")) if "evidence" not in path.name.lower())
    for candidate in candidates:
        if candidate.exists() and candidate.suffix.lower() == ".json":
            target = work_dir / settings.s2_toc_output_file_name
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
    target = work_dir / settings.s2_toc_output_file_name
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _resolve_wiki_dir(project: dict[str, Any], project_dir: Path, work_dir: Path) -> Path | None:
    project_id = str(project.get("id") or "")
    parse_storage = project.get("parse_storage") or {}
    candidates = [root / "s2_toc_workdir" / "wiki" for root in legacy_workspace_roots(project_id, parse_storage)]
    for candidate in candidates:
        if (candidate / "卡片").exists():
            target = work_dir / "wiki"
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(candidate, target, dirs_exist_ok=True)
            return target
    return None


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
            "receivedAt": _now_iso(),
            "parts": [{"type": "text", "text": result.stdout.strip()}],
        },
    )
    return payload


def _build_gap_planner_prompt(manifest_path: Path) -> str:
    return f"""
Use the {TECHNICAL_GAP_PLANNER_SKILL_NAME} skill.

你现在在做 S3 技术标缺口识别。后端已经准备好 manifest，其中包含人工确认后的目录 JSON、招标解析结构化结果、S2 素材 Wiki 副本、项目/客户/通用素材边界、素材索引、项目身份信息和人工确认的投标机型信息。

manifest：{manifest_path}

请直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 1800000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径。命令会把完整 gap_plan.json 写入 manifest 指定路径，并只在 stdout 打印小型摘要 JSON：

s4gap {manifest_path}

只返回命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
返回格式必须是：
{{
  "schema_version": "{TECHNICAL_GAP_PLAN_SCHEMA_VERSION}",
  "outputFile": "/data/documents/PRJ-0001/technical-workspace/s4_gap_workdir/gap_plan.json",
  "summary": {{"totalTocItems": 0, "matchedCount": 0, "missingCount": 0, "resolvedCount": 0, "ignoredCount": 0, "structuralCount": 0, "fillableTaskCount": 0, "blockingCount": 0}},
  "itemCount": 0
}}
""".strip()


def run_technical_gap_planner_skill(manifest_path: Path) -> dict[str, Any]:
    prompt = _build_gap_planner_prompt(manifest_path)
    try:
        return OpencodeClient().run_bid_tech_gap_planner_with_trace(prompt)
    except Exception:
        return _run_local_skill_runner(GAP_PLANNER_RUNNER, manifest_path, TECHNICAL_GAP_PLAN_SCHEMA_VERSION)


def build_technical_gap_plan_for_project(project: dict[str, Any]) -> dict[str, Any]:
    project_id = str(project.get("id") or "")
    project_dir = _project_dir(project)
    work_dir = technical_workspace_stage_dir(project_id, "s4_gap_workdir")
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
    wiki_dir = _resolve_wiki_dir(project, project_dir, work_dir)
    turbine_model = project_turbine_model(project)
    material_scope = build_project_material_scope(project)
    material_index = _allowed_technical_material_index(material_scope, turbine_model)
    bid_type = require_bid_type(
        project.get("bidType"),
        error_message="技术标缺口规划必须显式传入技术标项目。",
    )
    manifest = {
        "projectId": project_id,
        "projectName": str(project.get("name") or project_id),
        "bidType": bid_type,
        "workDir": str(work_dir),
        "tocJsonPath": str(toc_json_path),
        "wikiDir": str(wiki_dir) if wiki_dir else "",
        "parseResultPath": str(parse_result_path),
        "projectIdentity": project.get("identity") or {},
        "materialScope": material_scope,
        "materialIndex": material_index,
        "projectTurbineModel": turbine_model,
        "outputFile": str(output_file),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    result = run_technical_gap_planner_skill(manifest_path)
    plan_path = Path(str(result.get("outputFile") or output_file))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    _validate_technical_gap_plan_toc_coverage(plan, toc_json_path)
    plan["projectTurbineModel"] = turbine_model
    plan["planFile"] = str(plan_path)
    plan["manifestPath"] = str(manifest_path)
    plan["phase"] = "gap_detection"
    plan["scopeBoundary"] = material_scope
    normalize_technical_gap_plan_fill_task_skills(plan)
    plan["opencodeOutput"] = result.get("opencodeOutput") or {
        "status": "received",
        "sessionId": str(manifest_path),
        "providerId": "local-skill",
        "modelId": TECHNICAL_GAP_PLANNER_SKILL_NAME,
        "receivedAt": _now_iso(),
        "parts": [{"type": "text", "text": json.dumps({"outputFile": str(plan_path)}, ensure_ascii=False)}],
    }
    return plan
