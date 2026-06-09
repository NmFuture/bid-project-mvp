from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.services.opencode_client import OpencodeClient


SKILL_NAME = "bid-business-template-extractor"
SCHEMA_VERSION = "bid-business-template-extractor-v1"
BOUNDARY_DECISIONS_SCHEMA_VERSION = "bid-business-template-extractor-boundary-decisions-v1"
TEMPLATE_BOUNDARY_AGENT_MAX_ATTEMPTS = 3


def backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def skill_runner_path() -> Path:
    return backend_root() / "opencode" / "skill" / SKILL_NAME / "scripts" / "run_from_manifest.py"


def btplbound_runner_path() -> Path:
    return backend_root() / "opencode" / "skill" / SKILL_NAME / "scripts" / "btplbound_workflow.py"


def build_business_template_extractor_manifest(
    *,
    project_id: str,
    documents: list[dict[str, Any]],
    output_dir: Path,
    stage: str = "prepare",
    fallback_mode: str = "",
) -> dict[str, Any]:
    manifest_documents: list[dict[str, Any]] = []
    for document in documents:
        source_path = Path(str(document.get("sourcePath") or ""))
        if source_path.suffix.lower() != ".docx":
            continue
        manifest_documents.append(
            {
                "id": str(document.get("id") or ""),
                "name": str(document.get("name") or source_path.name),
                "sourcePath": str(source_path),
                "textPath": str(document.get("textPath") or ""),
            }
        )
    manifest: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "skillName": SKILL_NAME,
        "projectId": project_id,
        "outputDir": str(output_dir),
        "stage": stage,
        "documents": manifest_documents,
    }
    if fallback_mode:
        manifest["fallbackMode"] = fallback_mode
    return manifest


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_skill_manifest(manifest_path: Path) -> str:
    runner = skill_runner_path()
    completed = subprocess.run(
        [sys.executable, str(runner), str(manifest_path)],
        cwd=str(backend_root()),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"退出码 {completed.returncode}"
        raise RuntimeError(message)
    return completed.stdout


def _run_btplbound_command(command: str, manifest_path: Path, *args: object) -> dict[str, Any]:
    runner = btplbound_runner_path()
    completed = subprocess.run(
        [sys.executable, str(runner), command, str(manifest_path), *(str(arg) for arg in args)],
        cwd=str(backend_root()),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
        raise RuntimeError(f"btplbound {command} failed: {message}")
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"btplbound {command} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"btplbound {command} returned non-object JSON")
    return payload


def _load_btplbound_status(manifest_path: Path) -> dict[str, Any]:
    return _run_btplbound_command("status", manifest_path)


def _btplbound_status_is_ready(status: dict[str, Any]) -> bool:
    if str(status.get("status") or "").strip().lower() == "ready":
        return True
    candidate = status.get("candidate") if isinstance(status.get("candidate"), dict) else {}
    boundary = status.get("boundary") if isinstance(status.get("boundary"), dict) else {}
    return (
        int(candidate.get("pendingBatchCount") or 0) == 0
        and int(boundary.get("pendingBatchCount") or 0) == 0
        and int(candidate.get("decidedBatchCount") or 0) == int(candidate.get("batchCount") or 0)
        and int(boundary.get("decidedBatchCount") or 0) == int(boundary.get("batchCount") or 0)
    )


def _compact_btplbound_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": str(status.get("status") or ""),
        "candidate": status.get("candidate") if isinstance(status.get("candidate"), dict) else {},
        "boundary": status.get("boundary") if isinstance(status.get("boundary"), dict) else {},
    }


def _append_boundary_attempt_trace(
    traces: list[dict[str, Any]],
    *,
    attempt: int,
    status: dict[str, Any] | None = None,
    trace: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    item: dict[str, Any] = {"attempt": attempt}
    if status is not None:
        item["status"] = _compact_btplbound_status(status)
    if trace:
        item["opencodeOutput"] = trace
        for key in ("sessionId", "providerId", "modelId", "receivedAt", "completionSource"):
            if key in trace:
                item[key] = trace[key]
    if error:
        item["error"] = error
    traces.append(item)


def _finalize_btplbound_decisions_if_ready(manifest_path: Path) -> dict[str, Any] | None:
    status = _load_btplbound_status(manifest_path)
    if not _btplbound_status_is_ready(status):
        return None
    return _run_btplbound_command("finalize", manifest_path)


def _combine_boundary_agent_trace(traces: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not traces:
        return None
    for item in reversed(traces):
        trace = item.get("opencodeOutput")
        if isinstance(trace, dict):
            combined = dict(trace)
            combined["boundaryAgentAttempts"] = traces
            combined["boundaryAgentAttemptCount"] = len(traces)
            return combined
    return {"status": "received", "boundaryAgentAttempts": traces, "boundaryAgentAttemptCount": len(traces)}


def _load_extraction_payload(output_dir: Path) -> dict[str, Any] | None:
    result_path = output_dir / "business_template_extraction.json"
    if not result_path.is_file():
        return None
    return json.loads(result_path.read_text(encoding="utf-8"))


def _document_output_dirs(payload: dict[str, Any], output_dir: Path) -> list[Path]:
    dirs: list[Path] = []
    for document in payload.get("documents") or []:
        if not isinstance(document, dict):
            continue
        raw_output_dir = str(document.get("outputDir") or "").strip()
        if raw_output_dir:
            dirs.append(Path(raw_output_dir))
    if dirs:
        return dirs
    return [path for path in output_dir.iterdir() if path.is_dir()] if output_dir.is_dir() else []


def _read_json_or(path: Path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _summarize_candidates(document_output: Path, *, max_items: int = 80) -> dict[str, Any]:
    candidates = _read_json_or(document_output / "candidate_templates.json", [])
    regions = _read_json_or(document_output / "regions.json", [])
    blocks = _read_json_or(document_output / "blocks.json", [])
    summarized_candidates: list[dict[str, Any]] = []
    if isinstance(candidates, list):
        for candidate in candidates[:max_items]:
            if not isinstance(candidate, dict):
                continue
            summarized_candidates.append(
                {
                    "candidateId": str(candidate.get("candidateId") or ""),
                    "candidateBlockId": candidate.get("candidateBlockId"),
                    "title": str(candidate.get("text") or candidate.get("title") or ""),
                    "regionId": str(candidate.get("regionId") or ""),
                    "regionTitle": str(candidate.get("regionTitle") or ""),
                    "score": candidate.get("score"),
                    "signals": candidate.get("signals") if isinstance(candidate.get("signals"), list) else [],
                    "candidateTemplatesPath": str(document_output / "candidate_templates.json"),
                    "evidenceWindowPath": str(document_output / "candidate_windows.json"),
                    "batchManifestPath": str(document_output / "agent_decision_batches"),
                    "llmBoundaryDecisionsPath": str(document_output / "llm_boundary_decisions.json"),
                }
            )
    return {
        "documentOutputDir": str(document_output),
        "candidateTemplatesPath": str(document_output / "candidate_templates.json"),
        "candidateWindowsPath": str(document_output / "candidate_windows.json"),
        "llmBoundaryDecisionsPath": str(document_output / "llm_boundary_decisions.json"),
        "candidateCount": len(candidates) if isinstance(candidates, list) else 0,
        "regionCount": len(regions) if isinstance(regions, list) else 0,
        "candidates": summarized_candidates,
        "regions": regions,
        "blockCount": len(blocks) if isinstance(blocks, list) else 0,
    }


def build_business_template_boundary_decision_prompt(
    *,
    project_id: str,
    manifest_path: Path,
    output_dir: Path,
    prepare_payload: dict[str, Any],
    attempt: int = 1,
    max_attempts: int = TEMPLATE_BOUNDARY_AGENT_MAX_ATTEMPTS,
    current_status: dict[str, Any] | None = None,
) -> str:
    documents = [_summarize_candidates(path) for path in _document_output_dirs(prepare_payload, output_dir)]
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "boundaryDecisionSchemaVersion": BOUNDARY_DECISIONS_SCHEMA_VERSION,
        "projectId": project_id,
        "manifestPath": str(manifest_path),
        "outputDir": str(output_dir),
        "attempt": attempt,
        "maxAttempts": max_attempts,
        "currentStatus": _compact_btplbound_status(current_status or {}),
        "documents": documents,
    }
    return f"""
Use the {SKILL_NAME} skill.

你正在执行商务标模板提取的 Agent 边界裁决阶段。后端已经完成 prepare，只生成高召回疑似标题与压缩证据文件；candidate_templates.json 不是脚本确认模板清单。不得直接切片，也不得依赖脚本兜底结果作答。

必须使用 btplbound 按下面流程分批裁决。btplbound 只负责取证、校验、保存进度和汇总，不会做模板语义判断，也不会调用外部大模型；标题角色与边界必须由你基于 evidenceBlocks / boundaryEvidenceBlocks / nextBoundaryReference 作出判断。不要直接读取完整 blocks.json；如需证据，只使用 btplbound 返回的压缩 evidenceBlocks。

命令流程：
1. `btplbound status {manifest_path}`
   - 这是第 {attempt}/{max_attempts} 次后端可恢复尝试；如果 status 显示已有已裁决批次，必须只从 `btplbound ... next` 返回的待处理批次继续，不要重写已经存在的 `candidate_decision_batch_*.json` 或 `boundary_decision_batch_*.json`。
2. 循环执行 `btplbound candidate-batch {manifest_path} next`，读取每批候选和证据。
3. 对每批候选写出候选裁决 JSON，然后执行 `btplbound candidate-decision {manifest_path} <批号> <裁决文件>`。
4. 候选批全部完成后，循环执行 `btplbound boundary-batch {manifest_path} next`。
5. 对每批已确认模板起点写出边界裁决 JSON，然后执行 `btplbound boundary-decision {manifest_path} <批号> <裁决文件>`。
6. 全部完成后必须执行 `btplbound finalize {manifest_path}`，并把该命令输出的终态 JSON 作为最终回答。

候选裁决文件结构：
{{
  "decisions": [
    {{
      "candidateId": "CAND-0001",
      "isTemplateStart": true,
      "headingRole": "template_start",
      "rejectReason": "",
      "templateTitle": "投标函",
      "templateType": "bid_letter",
      "confidence": 0.92,
      "reason": "标题后有正文、填写字段或签章栏。",
      "needsReview": false
    }}
  ]
}}

headingRole 必须取以下四类之一：
- `template_start`：正式模板起点，后续进入 boundary-batch，并作为边界参考。
- `section_container`：父级章节或容器标题，不输出模板，但必须作为边界参考阻断前一个模板。
- `boundary_only`：只表示新内容段的边界，不输出模板，但必须作为边界参考阻断前一个模板。
- `reject`：目录项、正文、噪声或无效标题，不输出模板，也不作为边界参考。

边界裁决文件结构：
{{
  "decisions": [
    {{
      "candidateId": "CAND-0001",
      "startBlockId": 10,
      "endBlockId": 25,
      "confidence": 0.92,
      "reason": "遇到下一个真实模板标题前截断。",
      "needsReview": false
    }}
  ]
}}

裁决规则：
1. candidate_templates.json 是高召回疑似标题，不是脚本确认模板；你必须通过 candidate-batch 对每个标题定角色。
2. 目录项、目录列表、封面字段不得作为正式模板，应标记为 reject。
3. `sub_table_code + near_following_table` 需要看标题语义；只有编号或编号+标段的子表（如“表2 E”“表3 A”“表1 A-1 标段一”）应归入最近的父级业务标题，不单独输出。
4. 子表标题含清晰业务名称（如“7D-1表 近年财务状况表”）时，可以判为 `template_start`；父标题后只接无业务名子表时，父标题应判为 `template_start` 并包含这些子表。
5. `承诺书/声明函/保密承诺书/保证函格式` 后接正文、填写字段或签章栏时，应判为 `template_start`；父级容器不能让整组子模板消失。
6. 边界阶段只能为 template_start 生成起终点。
7. section_container 和 boundary_only 不输出模板，但必须作为边界参考，阻断前一个 template_start。
8. 当前模板必须在下一个边界参考标题前结束，不能跨越 nextBoundaryReference。
9. startBlockId/endBlockId 必须留在投标/响应文件格式章节内，不得跨入合同附件、合同价格组成、履约保证金格式等排除章节。
10. 部分附件/占位类模板可以只有标题块；当 boundary-batch 返回 suggestedStartBlockId == maxEndBlockId 时，应提交相同的 startBlockId/endBlockId，不得为了形成多块范围跨越 nextBoundaryReference。
11. 标题后没有正文、表格、填写字段或签章栏时，只有附件/占位类模板可以作为正式模板；目录项、封面字段、正文噪声或无效标题仍必须 reject。
12. confidence < 0.75 或 needsReview=true 的候选只能进入 review.md，不得成为正式切片。

后端只提供摘要与文件路径，未内联候选证据正文。你必须通过 btplbound 读取证据并生成 llm_boundary_decisions.json。摘要如下：
{json.dumps(payload, ensure_ascii=False, indent=2)}

最终只返回 `btplbound finalize {manifest_path}` 输出的 JSON，不要返回 Markdown：
{{
  "schemaVersion": "{BOUNDARY_DECISIONS_SCHEMA_VERSION}",
  "decisionFiles": ["/abs/path/llm_boundary_decisions.json"],
  "summary": {{"documentCount": 1, "decisionCount": 1, "acceptedTemplateCount": 1, "rejectedCount": 0}}
}}
""".strip()


def _missing_decision_paths(prepare_payload: dict[str, Any], output_dir: Path) -> list[Path]:
    missing: list[Path] = []
    for document_output in _document_output_dirs(prepare_payload, output_dir):
        candidates_path = document_output / "candidate_templates.json"
        decisions_path = document_output / "llm_boundary_decisions.json"
        if candidates_path.is_file() and not decisions_path.is_file():
            missing.append(decisions_path)
    return missing


def _save_extraction_trace(
    payload: dict[str, Any],
    *,
    trace: dict[str, Any] | None = None,
    fallback_reason: str = "",
) -> None:
    if trace:
        payload["opencodeOutput"] = trace
    if fallback_reason:
        warnings = payload.setdefault("warnings", [])
        if isinstance(warnings, list):
            warnings.append(
                {
                    "code": "template_boundary_agent_failed",
                    "message": f"模板边界 Agent 裁决未完成，已显式启用脚本兜底：{fallback_reason}",
                }
            )
        if isinstance(warnings, list) and warnings:
            warnings[-1]["message"] = f"模板边界 Agent 裁决未完成，未启用脚本兜底：{fallback_reason}"
        quality = payload.setdefault("quality", {})
        if isinstance(quality, dict):
            quality["scriptFallbackUsed"] = bool(quality.get("scriptFallbackUsed"))
            quality["agentFallbackReason"] = fallback_reason

    raw_output_dir = str(payload.get("outputDir") or "").strip()
    if raw_output_dir:
        result_path = Path(raw_output_dir) / "business_template_extraction.json"
        if result_path.parent.is_dir():
            result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def convert_extractor_appendices(payload: dict[str, Any]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for raw in payload.get("appendices") or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("evidence") or "").strip()
        docx_path = str(raw.get("docxPath") or "").strip()
        if not title or not docx_path:
            continue
        converted.append(
            {
                "id": str(raw.get("id") or f"APPX-{len(converted) + 1:04d}"),
                "title": title,
                "evidence": str(raw.get("evidence") or title),
                "artifactType": "business_attachment_template",
                "templateType": str(raw.get("templateType") or "business_template"),
                "templateSectionTitle": str(raw.get("templateSectionTitle") or ""),
                "status": str(raw.get("status") or "generated"),
                "rowCount": int(raw.get("rowCount") or 0),
                "docxPath": docx_path,
                "workspacePath": str(raw.get("workspacePath") or ""),
                "sourceDocumentId": str(raw.get("sourceDocumentId") or ""),
                "sourceDocumentName": str(raw.get("sourceDocumentName") or ""),
                "sourcePath": str(raw.get("sourcePath") or ""),
                "extractionMode": "business_template_extractor_skill",
                "startBlockIndex": raw.get("startBlockIndex"),
                "endBlockIndex": raw.get("endBlockIndex"),
                "quality": raw.get("quality") if isinstance(raw.get("quality"), dict) else {},
            }
        )
    return converted


def run_business_template_extractor(
    *,
    project_id: str,
    documents: list[dict[str, Any]],
    project_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    output_dir = project_dir / "business_template_extraction"
    manifest_path = project_dir / "business_template_extraction_manifest.json"
    manifest = build_business_template_extractor_manifest(
        project_id=project_id,
        documents=documents,
        output_dir=output_dir,
        stage="prepare",
    )
    _write_manifest(manifest_path, manifest)
    if not manifest["documents"]:
        return [], None, "未找到可用于商务模板提取 skill 的 DOCX 招标文件。"

    try:
        _run_skill_manifest(manifest_path)
    except RuntimeError as exc:
        return [], None, f"商务模板提取 skill prepare 阶段失败：{exc}"

    prepare_payload = _load_extraction_payload(output_dir)
    if prepare_payload is None:
        return [], None, "商务模板提取 skill prepare 阶段未生成 business_template_extraction.json。"

    boundary_attempts: list[dict[str, Any]] = []
    fallback_reason = ""
    last_error = ""
    for attempt in range(1, TEMPLATE_BOUNDARY_AGENT_MAX_ATTEMPTS + 1):
        try:
            status = _load_btplbound_status(manifest_path)
            if _btplbound_status_is_ready(status):
                _append_boundary_attempt_trace(boundary_attempts, attempt=attempt, status=status)
                break

            prompt = build_business_template_boundary_decision_prompt(
                project_id=project_id,
                manifest_path=manifest_path,
                output_dir=output_dir,
                prepare_payload=prepare_payload,
                attempt=attempt,
                max_attempts=TEMPLATE_BOUNDARY_AGENT_MAX_ATTEMPTS,
                current_status=status,
            )
            decision_result = OpencodeClient().decide_business_template_boundaries_with_trace(prompt)
            trace = decision_result.get("opencodeOutput") if isinstance(decision_result.get("opencodeOutput"), dict) else None
            status_after = _load_btplbound_status(manifest_path)
            _append_boundary_attempt_trace(boundary_attempts, attempt=attempt, status=status_after, trace=trace)
            if _btplbound_status_is_ready(status_after):
                break
            if not _missing_decision_paths(prepare_payload, output_dir):
                break
        except Exception as exc:
            last_error = str(exc)
            try:
                error_status = _load_btplbound_status(manifest_path)
            except Exception:
                error_status = None
            _append_boundary_attempt_trace(boundary_attempts, attempt=attempt, status=error_status, error=last_error)

    opencode_trace = _combine_boundary_agent_trace(boundary_attempts)
    try:
        finalized = _finalize_btplbound_decisions_if_ready(manifest_path)
        if finalized is None:
            missing = _missing_decision_paths(prepare_payload, output_dir)
            if last_error:
                fallback_reason = last_error
                if missing:
                    fallback_reason += "；缺少 Agent 裁决文件：" + ", ".join(str(path) for path in missing)
            elif missing:
                fallback_reason = "缺少 Agent 裁决文件：" + ", ".join(str(path) for path in missing)
            else:
                status = _load_btplbound_status(manifest_path)
                fallback_reason = f"btplbound decisions incomplete after {TEMPLATE_BOUNDARY_AGENT_MAX_ATTEMPTS} attempts: {_compact_btplbound_status(status)}"
    except Exception as exc:
        fallback_reason = str(exc)

    finalize_manifest = build_business_template_extractor_manifest(
        project_id=project_id,
        documents=documents,
        output_dir=output_dir,
        stage="finalize",
        fallback_mode="",
    )
    _write_manifest(manifest_path, finalize_manifest)
    try:
        _run_skill_manifest(manifest_path)
    except RuntimeError as exc:
        return [], prepare_payload, f"商务模板提取 skill finalize 阶段失败：{exc}"

    payload = _load_extraction_payload(output_dir)
    if payload is None:
        return [], None, "商务模板提取 skill 未生成 business_template_extraction.json。"
    _save_extraction_trace(payload, trace=opencode_trace, fallback_reason=fallback_reason)
    appendices = convert_extractor_appendices(payload)
    if not appendices:
        return [], payload, "商务模板提取 skill 未识别到模板。"
    return appendices, payload, ""
