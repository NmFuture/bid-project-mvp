from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from app.services.bid_parse_cancel import ParseCancelledError
from app.services.opencode_client import OpencodeClient


SKILL_NAME = "bid-business-template-extractor"
SCHEMA_VERSION = "bid-business-template-extractor-v1"
TEMPLATE_EXTRACTION_AGENT_TIMEOUT_MS = 300_000


def backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def btplnav_runner_path() -> Path:
    return backend_root() / "opencode" / "skills" / SKILL_NAME / "scripts" / "run_from_manifest.py"


def _raise_if_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise ParseCancelledError("解析已取消。")


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
        document_nav_path = str(document.get("documentNavPath") or "").strip()
        is_docx = source_path.suffix.lower() == ".docx"
        is_pdf_with_nav = source_path.suffix.lower() == ".pdf" and document_nav_path
        if not is_docx and not is_pdf_with_nav:
            continue
        item = {
            "id": str(document.get("id") or ""),
            "name": str(document.get("name") or source_path.name),
            "sourcePath": str(source_path),
            "textPath": str(document.get("textPath") or ""),
        }
        if document_nav_path:
            item["documentNavPath"] = document_nav_path
        document_parse_engine = str(document.get("documentParseEngine") or "").strip()
        if document_parse_engine:
            item["documentParseEngine"] = document_parse_engine
        manifest_documents.append(item)
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


def _run_btplnav_command(
    command: str,
    manifest_path: Path,
    *args: object,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    runner = btplnav_runner_path()
    command_args = [sys.executable, str(runner), command, str(manifest_path), *(str(arg) for arg in args)]
    if cancel_check is None:
        completed = subprocess.run(
            command_args,
            cwd=str(backend_root()),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
    else:
        process = subprocess.Popen(
            command_args,
            cwd=str(backend_root()),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        while process.poll() is None:
            if cancel_check():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                raise ParseCancelledError("解析已取消。")
            time.sleep(0.2)
        stdout, stderr = process.communicate()
        completed = subprocess.CompletedProcess(command_args, process.returncode, stdout, stderr)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
        raise RuntimeError(f"btplnav {command} failed: {message}")
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"btplnav {command} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"btplnav {command} returned non-object JSON")
    return payload


def _trace_from_exception(exc: Exception) -> dict[str, Any] | None:
    trace = getattr(exc, "opencode_trace", None)
    return trace if isinstance(trace, dict) else None


def _load_extraction_payload(output_dir: Path) -> dict[str, Any] | None:
    result_path = output_dir / "business_template_extraction.json"
    if not result_path.is_file():
        return None
    return json.loads(result_path.read_text(encoding="utf-8"))


def _hydrate_payload_source_engines(payload: dict[str, Any], documents: list[dict[str, Any]]) -> bool:
    engines_by_document = {
        str(document.get("id") or "").strip(): str(
            document.get("documentParseEngine") or document.get("sourceEngine") or ""
        ).strip()
        for document in documents
        if str(document.get("id") or "").strip()
    }
    changed = False
    for raw in payload.get("appendices") or []:
        if not isinstance(raw, dict):
            continue
        document_id = str(raw.get("sourceDocumentId") or "").strip()
        source_engine = str(raw.get("sourceEngine") or "").strip() or engines_by_document.get(document_id, "")
        if not source_engine:
            continue
        if not str(raw.get("sourceEngine") or "").strip():
            raw["sourceEngine"] = source_engine
            changed = True
        quality = raw.setdefault("quality", {})
        if isinstance(quality, dict) and not str(quality.get("sourceEngine") or "").strip():
            quality["sourceEngine"] = source_engine
            changed = True
    quality = payload.setdefault("quality", {})
    payload_source_engine = ""
    if isinstance(quality, dict):
        payload_source_engine = str(quality.get("sourceEngine") or "").strip()
    appendix_engines = {
        str(raw.get("sourceEngine") or "").strip()
        for raw in payload.get("appendices") or []
        if isinstance(raw, dict) and str(raw.get("sourceEngine") or "").strip()
    }
    if isinstance(quality, dict) and not payload_source_engine and len(appendix_engines) == 1:
        quality["sourceEngine"] = next(iter(appendix_engines))
        changed = True
    return changed


def _existing_finalized_payload(
    output_dir: Path,
    documents: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    payload = _load_extraction_payload(output_dir)
    if not payload or str(payload.get("stage") or "") != "finalize":
        return None
    changed = _hydrate_payload_source_engines(payload, documents)
    appendices = convert_extractor_appendices(payload)
    if not appendices:
        return None

    document_ids = {str(document.get("id") or "").strip() for document in documents}
    document_ids.discard("")
    if not document_ids:
        return None
    appendix_document_ids = {
        str(appendix.get("sourceDocumentId") or "").strip()
        for appendix in appendices
        if str(appendix.get("sourceDocumentId") or "").strip()
    }
    if appendix_document_ids and not appendix_document_ids.issubset(document_ids):
        return None
    if any(not Path(str(appendix.get("docxPath") or "")).is_file() for appendix in appendices):
        return None
    if changed:
        result_path = output_dir / "business_template_extraction.json"
        result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return appendices, payload


def build_business_template_navigation_prompt(
    *,
    project_id: str,
    manifest_path: Path,
) -> str:
    return f"""
Use the {SKILL_NAME} skill.

你是招投标专家、模板提取者和边界裁决者。脚本只提供 DOCX 导航阅读器、块号尺子、Word 切片器和结构校验器；不要等待脚本给候选标题，也不要让脚本替你判断“投标文件格式”章节在哪里。

请用 Bash 执行 `btplnav` 小输出工作流，timeout 设置为 600000 毫秒或更高：

btplnav prepare {manifest_path}
btplnav overview {manifest_path} --page 1 --page-size 40
btplnav search {manifest_path} "<query>" --limit 20
btplnav window {manifest_path} <sourceDocumentId> <blockId> --before 4 --after 10
btplnav read {manifest_path} <sourceDocumentId> <startBlockId> <endBlockId> --max-chars 4000
btplnav submit {manifest_path} templates '<json>'
btplnav validate {manifest_path}
btplnav status {manifest_path}
btplnav finalize {manifest_path}

工作要求：
- 遵循 skill 中的执行流程，自主浏览全文，按语义找到商务标投标/响应文件格式相关区域；该区域可能会划分商务部分和技术部分，只提取商务部分；再建立粗章节地图；不要依赖固定标题或固定搜索词。
- 必须逐个粗章节内部下钻；遇到层级子项、表格标题、独立文件标题、签章/填写区、证明材料位置时，用“是否能成为独立编制任务”裁决是否独立成模板。
- finalize 前必须做父级集合回查；父级范围若包含多个子项、多张表、多个文件格式或多项证明材料，继续回查并细拆。
- 自主识别模板并裁决边界，提交每个模板的 sourceDocumentId、title、templateType、startBlockId、endBlockId、confidence、reason；reason 要说明独立编制价值。
- 不要额外套用未写在 skill 里的排除清单；只根据 skill 流程、裁决准则和原文上下文判断。
- validate 只做结构校验，不代表业务粒度正确；validate 失败时用 overview/search/window/read 回查后重新 submit；不要编造块号。
- 必须执行 btplnav finalize，最终只返回 finalize stdout 的 JSON。

项目：{project_id}
manifest：{manifest_path}
""".strip()


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
                    "code": "business_template_agent_failed",
                    "message": f"商务模板提取 Agent 未完成，未启用脚本兜底：{fallback_reason}",
                }
            )
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
                "sourceFile": str(raw.get("sourceFile") or raw.get("sourceDocumentName") or ""),
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
    progress_callback=None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    _raise_if_cancelled(cancel_check)
    output_dir = project_dir / "business_template_extraction"
    manifest_path = project_dir / "business_template_extraction_manifest.json"
    existing = _existing_finalized_payload(output_dir, documents)
    if existing is not None:
        appendices, payload = existing
        return appendices, payload, ""

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
        _raise_if_cancelled(cancel_check)
        _run_btplnav_command("prepare", manifest_path, cancel_check=cancel_check)
        _raise_if_cancelled(cancel_check)
    except ParseCancelledError:
        raise
    except RuntimeError as exc:
        return [], None, f"商务模板提取 skill prepare 阶段失败：{exc}"

    prepare_payload = _load_extraction_payload(output_dir)
    fallback_reason = ""
    opencode_trace: dict[str, Any] | None = None

    def emit_session_ready(details: dict[str, Any]) -> None:
        if progress_callback:
            progress_callback(
                "business_template_extraction_agent",
                {
                    **details,
                    "status": "running",
                    "parts": [{"type": "text", "text": "opencode session 已建立，正在识别商务模板。"}],
                },
            )

    try:
        _raise_if_cancelled(cancel_check)
        prompt = build_business_template_navigation_prompt(project_id=project_id, manifest_path=manifest_path)
        agent_result = OpencodeClient(timeout_ms=TEMPLATE_EXTRACTION_AGENT_TIMEOUT_MS).extract_business_templates_with_trace(
            prompt,
            session_ready_callback=emit_session_ready,
            cancel_check=cancel_check,
        )
        _raise_if_cancelled(cancel_check)
        opencode_trace = agent_result.get("opencodeOutput") if isinstance(agent_result.get("opencodeOutput"), dict) else None
        if opencode_trace and progress_callback:
            progress_callback("business_template_extraction_agent", opencode_trace)
    except ParseCancelledError:
        raise
    except Exception as exc:
        fallback_reason = str(exc)
        trace = _trace_from_exception(exc)
        if trace and progress_callback:
            progress_callback("business_template_extraction_agent", trace)
        opencode_trace = trace

    _raise_if_cancelled(cancel_check)
    payload = _load_extraction_payload(output_dir)
    if payload is None:
        try:
            _raise_if_cancelled(cancel_check)
            _run_btplnav_command("finalize", manifest_path, cancel_check=cancel_check)
            _raise_if_cancelled(cancel_check)
            payload = _load_extraction_payload(output_dir)
        except ParseCancelledError:
            raise
        except RuntimeError as exc:
            return [], prepare_payload, f"商务模板提取 skill finalize 阶段失败：{exc}"
    if payload is None:
        return [], None, "商务模板提取 skill 未生成 business_template_extraction.json。"
    _save_extraction_trace(payload, trace=opencode_trace, fallback_reason=fallback_reason)
    appendices = convert_extractor_appendices(payload)
    if not appendices:
        if fallback_reason:
            return [], payload, f"商务模板提取 Agent 未完成，未启用脚本兜底：{fallback_reason}"
        return [], payload, "商务模板提取 skill 未识别到模板。"
    return appendices, payload, ""
