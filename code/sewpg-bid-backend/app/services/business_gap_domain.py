from __future__ import annotations

import base64
import binascii
import copy
import re
from pathlib import Path
from typing import Any

from app.services.bid_type import BUSINESS_BID_TYPE
from app.services.file_utils import safe_filename
from app.services.material_folder_scope import project_material_root_path


def find_task(plan: dict[str, Any], task_id: str) -> dict[str, Any]:
    target = str(task_id or "")
    for task in plan.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        if target in {str(task.get("id") or ""), str(task.get("taskKey") or "")}:
            return task
    raise KeyError(task_id)


def find_toc_ref(plan: dict[str, Any], node_id: str) -> dict[str, Any]:
    target = str(node_id or "")
    for ref in plan.get("tocRefs") or []:
        if isinstance(ref, dict) and str(ref.get("nodeId") or "") == target:
            return ref
    raise KeyError(node_id)


def find_artifact_in_task(task: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    target = str(artifact_id or "")
    for artifact in task.get("resolvedArtifacts") or []:
        if isinstance(artifact, dict) and str(artifact.get("artifactId") or "") == target:
            return artifact
    raise KeyError(artifact_id)


def update_toc_ref_statuses(plan: dict[str, Any]) -> None:
    task_by_id = {
        str(task.get("id") or ""): task
        for task in plan.get("tasks") or []
        if isinstance(task, dict) and str(task.get("id") or "")
    }
    for ref in plan.get("tocRefs") or []:
        if not isinstance(ref, dict):
            continue
        bound = [task_by_id[task_id] for task_id in [str(item) for item in ref.get("taskIds") or []] if task_id in task_by_id]
        if not bound:
            ref["status"] = "empty"
        elif all(str(task.get("status") or "") in {"ready", "resolved", "ignored"} for task in bound):
            ref["status"] = "ready"
        elif any(str(task.get("status") or "") == "review_required" for task in bound):
            ref["status"] = "review_required"
        else:
            ref["status"] = "partial"


def task_can_ai_draft(task: dict[str, Any]) -> bool:
    task_type = str(task.get("taskType") or "")
    decision = str(task.get("decision") or "")
    assignee = str(task.get("assigneeMode") or "")
    title = str(task.get("title") or "")
    if task_type in {"certificate", "attachment", "bundle"}:
        return False
    if decision == "fill_required" or assignee in {"generate_or_fill", "ai_draft"}:
        return True
    return bool(re.search(r"投标函|授权|廉洁|承诺|声明|说明|专用章|履约", title))


def default_task_assembly_mode(module_key: str, task_type: str, decision: str, title: str) -> str:
    normalized = re.sub(r"[\s:：，,。.！!？?\-_/'\"“”‘’·（）()【】\[\]/]+", "", str(title or ""))
    if decision == "ai_draft_required":
        return "ai_draft"
    if task_type == "table":
        return "table_fill_from_material"
    if task_type == "certificate":
        return "embed_scan_or_image"
    if task_type == "attachment":
        if any(token in normalized for token in ["扫描", "回单", "保函", "证书", "图片", "pdf"]):
            return "embed_scan_or_image"
        return "attach_whole_file"
    if task_type == "bundle":
        if module_key in {"enterprise_finance_supply", "performance_cooperation_support"}:
            return "extract_and_summarize"
        return "attach_whole_file"
    if decision == "fill_required":
        return "template_fill_docx"
    if any(token in normalized for token in ["投标函", "授权", "廉洁", "承诺", "声明", "说明", "履约"]):
        return "template_fill_docx"
    return "extract_and_summarize"


def material_usage_for_assembly_mode(assembly_mode: str) -> str:
    return {
        "template_fill_docx": "fill_template",
        "table_fill_from_material": "fill_table",
        "attach_whole_file": "attach_whole",
        "embed_scan_or_image": "embed_scan",
        "extract_and_summarize": "extract_and_summarize",
        "extract_segment": "extract_segment",
        "ai_draft": "generate_draft",
        "manual_upload": "manual_upload",
    }.get(str(assembly_mode or ""), "")


def task_fill_plan(task: dict[str, Any]) -> dict[str, Any]:
    mode = str(task.get("assemblyMode") or default_task_assembly_mode(
        str(task.get("moduleKey") or ""),
        str(task.get("taskType") or ""),
        str(task.get("decision") or ""),
        str(task.get("title") or ""),
    ))
    plan = {
        "mode": mode,
        "materialUsage": str(task.get("materialUsage") or material_usage_for_assembly_mode(mode)),
        "requiresProjectFacts": mode in {"template_fill_docx", "table_fill_from_material", "extract_and_summarize", "ai_draft"},
        "requiresMaterialEvidence": mode in {"table_fill_from_material", "extract_and_summarize", "extract_segment", "attach_whole_file", "embed_scan_or_image"},
        "requiresHumanReview": True,
        "outputArtifactType": {
            "template_fill_docx": "filled_docx",
            "table_fill_from_material": "filled_table_docx",
            "attach_whole_file": "whole_file_attachment",
            "embed_scan_or_image": "embedded_scan",
            "extract_and_summarize": "extracted_summary_docx",
            "extract_segment": "extracted_segment_docx",
            "ai_draft": "ai_draft_docx",
        }.get(mode, "manual_artifact"),
    }
    if task.get("selectedEvidenceSegments"):
        plan["evidenceSegmentCount"] = len(task.get("selectedEvidenceSegments") or [])
    return plan


def assembly_mode_for_artifact(task: dict[str, Any], artifact: dict[str, Any]) -> str:
    usage = str(artifact.get("wikiUsageMode") or artifact.get("materialUsage") or "").strip().lower().replace("-", "_")
    usage_modes = {
        "attach_whole": "attach_whole_file",
        "attach_whole_file": "attach_whole_file",
        "embed_scan": "embed_scan_or_image",
        "embed_scan_or_image": "embed_scan_or_image",
        "extract_and_summarize": "extract_and_summarize",
        "summarize": "extract_and_summarize",
        "extract_summary": "extract_and_summarize",
        "extract_segment": "extract_segment",
        "fill_template": "template_fill_docx",
        "template_fill_docx": "template_fill_docx",
        "fill_table": "table_fill_from_material",
        "table_fill_from_material": "table_fill_from_material",
    }
    if usage in usage_modes:
        return usage_modes[usage]
    suffix = Path(str(artifact.get("fileName") or artifact.get("filePath") or "")).suffix.lower()
    mime_type = str(artifact.get("mimeType") or "").lower()
    task_mode = str(task.get("assemblyMode") or "")
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".pdf"} or "image/" in mime_type or "pdf" in mime_type:
        if task_mode in {"attach_whole_file", "extract_segment", "extract_and_summarize"}:
            return task_mode
        return "embed_scan_or_image"
    if task_mode:
        return task_mode
    return default_task_assembly_mode(
        str(task.get("moduleKey") or ""),
        str(task.get("taskType") or ""),
        str(task.get("decision") or ""),
        str(task.get("title") or ""),
    )


def artifact_matches_assembly_mode(task: dict[str, Any], artifact: dict[str, Any]) -> bool:
    mode = str(task.get("assemblyMode") or "")
    if not mode:
        return True
    artifact_mode = str(artifact.get("assemblyMode") or "")
    usage = str(artifact.get("wikiUsageMode") or artifact.get("materialUsage") or "")
    file_name = str(artifact.get("fileName") or artifact.get("materialName") or artifact.get("filePath") or "")
    suffix = Path(file_name).suffix.lower()
    source_mode = str(artifact.get("sourceMode") or "")
    artifact_type = str(artifact.get("artifactType") or "")
    if mode == "template_fill_docx":
        if artifact_mode == "template_fill_docx" or usage == "fill_template":
            return True
        if artifact_type == "parse_appendix_template" or source_mode == "parsed_from_tender_attachment_template":
            return True
        return suffix in {".doc", ".docx"} and bool(re.search(r"模板|格式|底稿|投标函|授权|廉洁|承诺|声明|说明|履约", file_name))
    if mode == "table_fill_from_material":
        return artifact_mode == mode or usage == "fill_table" or suffix in {".xls", ".xlsx", ".xlsm"}
    if mode == "embed_scan_or_image":
        return artifact_mode == mode or usage == "embed_scan" or suffix in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
    if mode == "attach_whole_file":
        return artifact_mode == mode or usage == "attach_whole"
    if mode == "extract_and_summarize":
        return (
            artifact_mode == mode
            or usage in {"extract_and_summarize", "summarize", "extract_summary", "extract_segment"}
            or bool(artifact.get("materialId"))
        )
    if mode == "extract_segment":
        return artifact_mode == mode or usage == "extract_segment" or bool(artifact.get("evidenceSegmentId"))
    if mode == "ai_draft":
        return artifact_mode == mode or usage == "generate_draft" or source_mode == "generated_by_business_s3_ai_draft"
    if mode == "manual_upload":
        return artifact_mode == mode or usage == "manual_upload" or source_mode == "uploaded_in_business_s3"
    return True


def candidate_matches_assembly_mode(task: dict[str, Any], candidate: dict[str, Any]) -> bool:
    mode = str(task.get("assemblyMode") or "")
    if not mode:
        return True
    usage = str(candidate.get("wikiUsageMode") or candidate.get("materialUsage") or "")
    file_name = str(candidate.get("materialName") or candidate.get("name") or candidate.get("fileName") or "")
    folder_path = str(candidate.get("folderPath") or candidate.get("path") or "")
    text = f"{file_name} {folder_path}"
    suffix = Path(file_name).suffix.lower()
    if mode == "template_fill_docx":
        return usage == "fill_template" or (
            suffix in {"", ".doc", ".docx"} and bool(re.search(r"模板|格式|底稿|投标函|授权|廉洁|承诺|声明|说明|履约", text))
        )
    if mode == "table_fill_from_material":
        return usage == "fill_table" or suffix in {".xls", ".xlsx", ".xlsm"} or bool(re.search(r"表|清单|报价|价格|规格|偏差", text))
    if mode == "embed_scan_or_image":
        return usage == "embed_scan" or suffix in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"} or bool(re.search(r"证书|扫描|图片|回单|保函", text))
    if mode == "attach_whole_file":
        return usage == "attach_whole"
    if mode == "extract_and_summarize":
        return usage in {"extract_and_summarize", "summarize", "extract_summary", "extract_segment"} or bool(candidate.get("materialId"))
    if mode == "extract_segment":
        return usage == "extract_segment" or bool(candidate.get("evidenceSegmentId"))
    if mode == "ai_draft":
        return usage == "generate_draft"
    if mode == "manual_upload":
        return usage == "manual_upload"
    return True


def recompute_task_after_artifact_change(task: dict[str, Any]) -> None:
    flags = task.setdefault("riskFlags", [])
    if not isinstance(flags, list):
        flags = []
        task["riskFlags"] = flags
    for stale_flag in (
        "missing_material",
        "manual_upload_required",
        "template_missing_for_fill",
        "candidate_template_unconfirmed",
    ):
        if stale_flag in flags:
            flags.remove(stale_flag)
    artifacts = [item for item in task.get("resolvedArtifacts") or [] if isinstance(item, dict)]
    mode_artifacts = [
        item
        for item in artifacts
        if artifact_matches_assembly_mode(task, item)
    ]
    confirmed_artifacts = [item for item in mode_artifacts if bool(item.get("confirmed"))]
    template_candidates = [item for item in task.get("templateCandidates") or [] if isinstance(item, dict)]
    candidates = [item for item in task.get("candidateMaterials") or [] if isinstance(item, dict)]
    mode_candidates = [
        item
        for item in candidates
        if candidate_matches_assembly_mode(task, item)
    ]
    if confirmed_artifacts:
        task["decision"] = "ready"
        task["status"] = "ready"
        return
    if mode_artifacts:
        task["decision"] = "review_required"
        task["status"] = "review_required"
        return
    if str(task.get("assemblyMode") or "") == "template_fill_docx" and template_candidates:
        task["decision"] = "review_required"
        task["status"] = "review_required"
        if "candidate_template_unconfirmed" not in flags:
            flags.append("candidate_template_unconfirmed")
        return
    if str(task.get("assemblyMode") or "") == "ai_draft":
        task["decision"] = "ai_draft_required"
        task["status"] = "needs_input"
        if "ai_draft_required" not in flags:
            flags.append("ai_draft_required")
        return
    if mode_candidates:
        task["decision"] = "review_required"
        task["status"] = "review_required"
        if str(task.get("assemblyMode") or "") == "template_fill_docx" and "candidate_template_unconfirmed" not in flags:
            flags.append("candidate_template_unconfirmed")
        return
    if str(task.get("assemblyMode") or "") == "template_fill_docx":
        task["decision"] = "fill_required"
        task["status"] = "needs_input"
        for flag in ("missing_material", "template_missing_for_fill"):
            if flag not in flags:
                flags.append(flag)
        return
    if str(task.get("sourceType") or "") == "manual_user":
        task["decision"] = "material_required"
        task["status"] = "needs_input"
        for flag in ("missing_material", "manual_upload_required"):
            if flag not in flags:
                flags.append(flag)
        return
    if str(task.get("taskType") or "") in {"attachment", "certificate", "bundle"} or str(task.get("decision") or "") == "material_required":
        task["decision"] = "material_required"
        task["status"] = "needs_input"
        if "missing_material" not in flags:
            flags.append("missing_material")
        return
    task["decision"] = "review_required"
    task["status"] = "review_required"


def apply_task_artifact_intent(task: dict[str, Any], artifacts: list[dict[str, Any]]) -> None:
    selected = next((artifact for artifact in artifacts if isinstance(artifact, dict)), None)
    if selected:
        task["assemblyMode"] = str(selected.get("assemblyMode") or task.get("assemblyMode") or "")
        task["materialUsage"] = str(selected.get("materialUsage") or task.get("materialUsage") or "")
    if not task.get("assemblyMode"):
        task["assemblyMode"] = default_task_assembly_mode(
            str(task.get("moduleKey") or ""),
            str(task.get("taskType") or ""),
            str(task.get("decision") or ""),
            str(task.get("title") or ""),
        )
    if not task.get("materialUsage"):
        task["materialUsage"] = material_usage_for_assembly_mode(str(task.get("assemblyMode") or ""))
    segments: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_segment_from_values(
        *,
        segment_id: str,
        title: str = "",
        material_id: str = "",
        material_name: str = "",
        wiki_card_id: str = "",
        source_pages: str = "",
        summary: str = "",
        usage_mode: str = "",
    ) -> None:
        clean_id = str(segment_id or "").strip()
        if not clean_id or clean_id in seen:
            return
        seen.add(clean_id)
        segments.append(
            {
                "segmentId": clean_id,
                "title": str(title or ""),
                "materialId": str(material_id or ""),
                "materialName": str(material_name or ""),
                "wikiCardId": str(wiki_card_id or ""),
                "sourcePages": str(source_pages or ""),
                "summary": str(summary or ""),
                "usageMode": str(usage_mode or ""),
            }
        )

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        nested_segments = artifact.get("selectedEvidenceSegments") if isinstance(artifact.get("selectedEvidenceSegments"), list) else []
        for raw_segment in nested_segments:
            if not isinstance(raw_segment, dict):
                continue
            add_segment_from_values(
                segment_id=str(raw_segment.get("segmentId") or raw_segment.get("evidenceSegmentId") or ""),
                title=str(raw_segment.get("title") or raw_segment.get("evidenceSegmentTitle") or ""),
                material_id=str(raw_segment.get("materialId") or artifact.get("materialId") or ""),
                material_name=str(raw_segment.get("materialName") or artifact.get("materialName") or ""),
                wiki_card_id=str(raw_segment.get("wikiCardId") or artifact.get("wikiCardId") or ""),
                source_pages=str(raw_segment.get("sourcePages") or raw_segment.get("evidenceSourcePages") or ""),
                summary=str(raw_segment.get("summary") or raw_segment.get("evidenceSummary") or ""),
                usage_mode=str(raw_segment.get("usageMode") or raw_segment.get("wikiUsageMode") or artifact.get("wikiUsageMode") or artifact.get("materialUsage") or ""),
            )
        segment_id = str(artifact.get("evidenceSegmentId") or "").strip()
        add_segment_from_values(
            segment_id=segment_id,
            title=str(artifact.get("evidenceSegmentTitle") or ""),
            material_id=str(artifact.get("materialId") or ""),
            material_name=str(artifact.get("materialName") or ""),
            wiki_card_id=str(artifact.get("wikiCardId") or ""),
            source_pages=str(artifact.get("evidenceSourcePages") or ""),
            summary=str(artifact.get("evidenceSummary") or ""),
            usage_mode=str(artifact.get("wikiUsageMode") or artifact.get("materialUsage") or ""),
        )
    if segments:
        current = [item for item in task.get("selectedEvidenceSegments") or [] if isinstance(item, dict)]
        incoming_ids = {str(item.get("segmentId") or "") for item in segments if str(item.get("segmentId") or "")}
        by_id = {
            str(item.get("segmentId") or ""): item
            for item in current
            if str(item.get("segmentId") or "") and str(item.get("segmentId") or "") not in incoming_ids
        }
        for segment in segments:
            by_id[str(segment.get("segmentId") or "")] = segment
        task["selectedEvidenceSegments"] = [*segments, *by_id.values()][:12]
    task["fillPlan"] = task_fill_plan(task)


def default_material_target_path(project_id: str, task: dict[str, Any]) -> str:
    root = project_material_root_path(BUSINESS_BID_TYPE, safe_filename(project_id, "project"))
    module_key = str(task.get("moduleKey") or "")
    task_type = str(task.get("taskType") or "")
    sub_module = str(task.get("subModuleKey") or "")
    title = str(task.get("title") or "")
    if module_key == "qualification_compliance_certificates" and (
        sub_module == "special_certificates" or task_type == "certificate" or "认证" in title or "证书" in title
    ):
        return f"{root}/资格审查与商务响应成册"
    if module_key in {"base_documents_guarantees", "structured_response_tables", "commitments_and_notes"}:
        return f"{root}/资格审查与商务响应成册"
    if module_key == "performance_cooperation_support":
        return f"{root}/招标要求与专项证明"
    return f"{root}/项目模板与过程稿"


def decode_upload_content(content: str, *, fallback_mime: str = "") -> tuple[bytes, str]:
    text = str(content or "").strip()
    if not text:
        return b"", fallback_mime
    if text.startswith("data:"):
        header, separator, payload = text.partition(",")
        if not separator:
            return b"", fallback_mime
        mime_type = header[5:].split(";", 1)[0] or fallback_mime
        if ";base64" in header.lower():
            try:
                return base64.b64decode(payload, validate=True), mime_type
            except (binascii.Error, ValueError) as exc:
                raise ValueError("上传文件 Base64 内容无法解析。") from exc
        return payload.encode("utf-8"), mime_type
    try:
        return base64.b64decode(text, validate=True), fallback_mime
    except (binascii.Error, ValueError):
        return text.encode("utf-8"), fallback_mime or "text/plain"


def unique_path(directory: Path, file_name: str) -> Path:
    target = directory / safe_filename(file_name, "artifact.bin")
    if not target.exists():
        return target
    stem = target.stem or "artifact"
    suffix = target.suffix
    for index in range(2, 1000):
        candidate = directory / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise ValueError(f"无法生成不重复的文件名：{file_name}")


def selected_material_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_entries = data.get("materials")
    if raw_entries is None:
        raw_entries = data.get("materialIds") or data.get("referenceMaterialIds") or []
    entries: list[dict[str, Any]] = []
    for entry in raw_entries if isinstance(raw_entries, list) else []:
        if isinstance(entry, str):
            entries.append({"materialId": entry})
        elif isinstance(entry, dict):
            entries.append(copy.deepcopy(entry))
    return entries


def selected_template_entry(task: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("template") if isinstance(data.get("template"), dict) else data
    template_id = str(raw.get("templateId") or "").strip() if isinstance(raw, dict) else ""
    file_path = str(raw.get("filePath") or raw.get("path") or "").strip() if isinstance(raw, dict) else ""
    for candidate in task.get("templateCandidates") or []:
        if not isinstance(candidate, dict):
            continue
        if template_id and template_id == str(candidate.get("templateId") or ""):
            return copy.deepcopy(candidate)
        if file_path and file_path == str(candidate.get("filePath") or candidate.get("path") or ""):
            return copy.deepcopy(candidate)
    if isinstance(raw, dict) and file_path:
        return copy.deepcopy(raw)
    raise ValueError("请选择一份有效模板候选。")


def table_fill_target(task: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("target") if isinstance(data.get("target"), dict) else {}
    target_id = str(raw.get("artifactId") or raw.get("templateId") or raw.get("id") or data.get("targetId") or "").strip()
    candidates = [
        item
        for item in [
            *(task.get("resolvedArtifacts") if isinstance(task.get("resolvedArtifacts"), list) else []),
            *(task.get("templateCandidates") if isinstance(task.get("templateCandidates"), list) else []),
            *(task.get("candidateMaterials") if isinstance(task.get("candidateMaterials"), list) else []),
        ]
        if isinstance(item, dict)
    ]
    if target_id:
        for candidate in candidates:
            ids = {
                str(candidate.get("artifactId") or ""),
                str(candidate.get("templateId") or ""),
                str(candidate.get("materialId") or ""),
                str(candidate.get("id") or ""),
                str(candidate.get("filePath") or ""),
                str(candidate.get("path") or ""),
            }
            if target_id in ids:
                return copy.deepcopy(candidate)
    if raw:
        return copy.deepcopy(raw)
    for candidate in candidates:
        if table_fill_target_looks_fillable(candidate):
            return copy.deepcopy(candidate)
    raise ValueError("请先选择一个待填写模板或附件。")


def table_fill_target_looks_fillable(item: dict[str, Any]) -> bool:
    name = (
        f"{item.get('fileName') or ''} {item.get('templateName') or ''} "
        f"{item.get('materialName') or ''} {item.get('name') or ''} "
        f"{item.get('title') or ''} {item.get('path') or ''} {item.get('folderPath') or ''}"
    )
    usage = str(item.get("materialUsage") or item.get("wikiUsageMode") or "")
    mode = str(item.get("assemblyMode") or "")
    return (
        mode in {"template_fill_docx", "table_fill_from_material"}
        or usage in {"fill_template", "fill_table"}
        or bool(re.search(r"表|报价|分项|偏差|规格|附件|模板|格式", name))
    )


def merge_material_refs(existing: list[Any], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*(existing or []), *(incoming or [])]:
        if not isinstance(item, dict):
            continue
        material_id = str(item.get("materialId") or item.get("id") or "").strip()
        if not material_id or material_id in seen:
            continue
        seen.add(material_id)
        merged.append(copy.deepcopy(item))
    return merged
