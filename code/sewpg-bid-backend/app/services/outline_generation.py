from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET

from app.core.config import settings
from app.services.store import build_directory_opencode_output, now_iso, store
from app.services.toc_engine import generate_toc_from_manifest

WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_TENDER_HINTS = 12
MAX_TEMPLATE_HINTS = 12
TOC_ENGINE_NAME = "local-rule-engine"

HEADING_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十百千0-9]+章[\s　].+"),
    re.compile(r"^第[一二三四五六七八九十百千0-9]+章.+"),
    re.compile(r"^[一二三四五六七八九十百千]+、.+"),
    re.compile(r"^\d+(\.\d+){0,3}[\s　].+"),
    re.compile(r"^附表[0-9一二三四五六七八九十]+.+"),
]


def generate_outline_for_project(project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return generate_outline_for_project_with_progress(project_id, data)


def generate_outline_for_project_with_progress(
    project_id: str,
    data: dict[str, Any] | None = None,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    project = store.get_project(project_id)
    parse_storage = store.get_parse_storage(project_id)
    tender_file_records, template_file_records = store.get_parse_inputs(project_id)
    combined_text_path = Path(str(parse_storage.get("combinedTextPath") or ""))
    if not combined_text_path.exists():
        raise ValueError("S1 解析结果不存在，请先完成解析。")

    combined_text = combined_text_path.read_text(encoding="utf-8").strip()
    if not combined_text:
        raise ValueError("S1 解析文本为空，暂时无法生成目录。")

    tender_hints = _extract_heading_candidates(combined_text, MAX_TENDER_HINTS)
    template_hints = _collect_template_hints(template_file_records)
    skill_workspace = _prepare_toc_skill_workspace(
        project_id=project_id,
        project=project,
        parse_storage=parse_storage,
        tender_file_records=tender_file_records,
        template_file_records=template_file_records,
    )
    if progress_callback:
        progress_callback(
            "inputs_ready",
            {
                "tenderHintCount": len(tender_hints),
                "templateHintCount": len(template_hints),
                "workDir": skill_workspace["workDir"],
                "bidType": skill_workspace["bidType"],
            },
        )

    if progress_callback:
        progress_callback(
            "generating_outline",
            {
                "templateHeadingCount": len(template_hints),
                "tenderCandidateCount": len(tender_hints),
            },
        )

    toc_result = generate_toc_from_manifest(skill_workspace)
    nodes = _nodes_from_generation_result(toc_result)
    summary = _summary_from_generation_result(toc_result)
    opencode_output = build_directory_opencode_output(status="not_used")
    opencode_output.update(
        {
            "engine": TOC_ENGINE_NAME,
            "workDir": skill_workspace["workDir"],
            "manifestPath": skill_workspace["manifestPath"],
            "canonicalManifestPath": skill_workspace["canonicalManifestPath"],
            "tocJsonPath": str(toc_result.get("outputFile") or skill_workspace["outputFile"]),
            "evidencePath": str(toc_result.get("evidenceFile") or skill_workspace["evidenceFile"]),
        }
    )
    if progress_callback:
        progress_callback(
            "normalizing_result",
            {
                "chapterCount": len(nodes),
            },
        )

    generated_at = now_iso()
    payload = store.save_generated_outline(
        project_id=project_id,
        nodes=nodes,
        generated_at=generated_at,
        summary=summary,
        opencode_output=opencode_output,
        rule_evidence=toc_result.get("ruleEvidence") if isinstance(toc_result.get("ruleEvidence"), dict) else {},
    )
    return payload


def _collect_template_hints(template_file_records: list[dict[str, Any]]) -> list[str]:
    hints: list[str] = []
    for file_record in template_file_records:
        path = Path(str(file_record.get("path") or ""))
        if not path.exists():
            continue
        if path.suffix.lower() == ".docx":
            hints.extend(_extract_docx_outline_hints(path, MAX_TEMPLATE_HINTS))
        if len(hints) >= MAX_TEMPLATE_HINTS:
            break
    seen: set[str] = set()
    ordered: list[str] = []
    for item in hints:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
        if len(ordered) >= MAX_TEMPLATE_HINTS:
            break
    return ordered


def _prepare_toc_skill_workspace(
    *,
    project_id: str,
    project: dict[str, Any],
    parse_storage: dict[str, Any],
    tender_file_records: list[dict[str, Any]],
    template_file_records: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_project_dir = str(parse_storage.get("projectDir") or "").strip()
    project_dir = Path(raw_project_dir).expanduser() if raw_project_dir else settings.parsed_dir / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    work_dir = project_dir / "s2_toc_workdir"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    tender_inputs = _copy_tender_inputs(tender_file_records, work_dir)
    template_path, attach_path = _copy_template_inputs(template_file_records, work_dir)
    bid_type = _normalize_bid_type(str(project.get("bidType") or "投标文件"))
    output_file = work_dir / _safe_file_name(settings.s2_toc_output_file_name, "toc.json")
    evidence_file = work_dir / _safe_file_name(settings.s2_toc_evidence_file_name, "toc_evidence.json")
    manifest_path = work_dir / "s2_input.json"
    manifest_alias_path = project_dir / "s2.json"
    manifest = {
        "projectId": project_id,
        "projectCode": str(project.get("projectCode") or project_id),
        "projectName": str(project.get("name") or project_id),
        "bidType": bid_type,
        "workDir": str(work_dir),
        "tenderFiles": tender_inputs,
        "templateFile": str(template_path) if template_path else "",
        "attachFile": str(attach_path) if attach_path else "",
        "outputFile": str(output_file),
        "evidenceFile": str(evidence_file),
        "rules": {
            "maxLevel": settings.s2_toc_max_level,
            "maxTenderCandidates": settings.s2_toc_max_tender_candidates,
            "maxTitleChars": settings.s2_toc_max_title_chars,
            "autoAppendTenderRequirements": settings.s2_toc_auto_append_tender_requirements,
        },
    }
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2)
    manifest_path.write_text(manifest_text, encoding="utf-8")
    manifest_alias_path.write_text(manifest_text, encoding="utf-8")
    return {
        **manifest,
        "manifestPath": str(manifest_alias_path),
        "canonicalManifestPath": str(manifest_path),
        "tenderFileCount": len(tender_inputs),
        "templateFileCount": 1 if template_path else 0,
        "hasAttachFile": bool(attach_path),
    }


def _copy_tender_inputs(file_records: list[dict[str, Any]], work_dir: Path) -> list[dict[str, str]]:
    copied: list[dict[str, str]] = []
    for index, record in enumerate(file_records, start=1):
        source = Path(str(record.get("path") or "")).expanduser()
        if not source.exists() or source.suffix.lower() != ".docx":
            continue
        name = _safe_file_name(str(record.get("name") or source.name), f"tender-{index}.docx")
        destination = _unique_path(work_dir / name)
        shutil.copy2(source, destination)
        copied.append(
            {
                "id": str(record.get("id") or f"tender-{index}"),
                "name": name,
                "path": str(destination),
                "originalPath": str(source),
            }
        )
    return copied


def _copy_template_inputs(file_records: list[dict[str, Any]], work_dir: Path) -> tuple[Path | None, Path | None]:
    docx_records = [
        record
        for record in file_records
        if Path(str(record.get("path") or "")).expanduser().exists()
        and Path(str(record.get("path") or "")).suffix.lower() == ".docx"
    ]
    attach_record = next((record for record in docx_records if _looks_like_attachment_template(record)), None)
    template_record = next(
        (
            record
            for record in docx_records
            if record is not attach_record
        ),
        None,
    )
    if template_record is None and docx_records:
        template_record = docx_records[0]

    template_path = (
        _copy_single_template(template_record, work_dir / "template-main.docx")
        if template_record is not None
        else None
    )
    attach_path = (
        _copy_single_template(attach_record, work_dir / "template-attachment.docx")
        if attach_record is not None and attach_record is not template_record
        else None
    )
    return template_path, attach_path


def _looks_like_attachment_template(record: dict[str, Any]) -> bool:
    role = str(record.get("role") or record.get("templateRole") or record.get("type") or "").lower()
    if role in {"attachment", "attachments", "appendix", "appendices", "attach"}:
        return True
    name = str(record.get("name") or Path(str(record.get("path") or "")).name)
    return bool(re.search(r"(附表|附件|appendix|attachment|attach)", name, re.IGNORECASE))


def _copy_single_template(record: dict[str, Any], destination: Path) -> Path:
    source = Path(str(record.get("path") or "")).expanduser()
    resolved_destination = destination.with_suffix(source.suffix.lower() or ".docx")
    shutil.copy2(source, resolved_destination)
    return resolved_destination


def _safe_file_name(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法为文件生成唯一路径：{path}")


def _normalize_bid_type(value: str) -> str:
    return value.strip() or "投标文件"


def _extract_docx_outline_hints(path: Path, limit: int) -> list[str]:
    hints: list[str] = []
    current_parts: list[str] = []

    def flush_paragraph() -> None:
        line = "".join(current_parts).strip()
        current_parts.clear()
        if not line:
            return
        if _looks_like_heading(line):
            hints.append(line)

    with zipfile.ZipFile(path) as archive:
        with archive.open("word/document.xml") as xml_file:
            for _, element in ET.iterparse(xml_file, events=("end",)):
                if element.tag == f"{WORD_NAMESPACE}t":
                    current_parts.append(element.text or "")
                elif element.tag == f"{WORD_NAMESPACE}tab":
                    current_parts.append(" ")
                elif element.tag in {f"{WORD_NAMESPACE}br", f"{WORD_NAMESPACE}cr"}:
                    current_parts.append(" ")
                elif element.tag == f"{WORD_NAMESPACE}p":
                    flush_paragraph()
                    element.clear()
                if len(hints) >= limit:
                    break
    return hints[:limit]


def _extract_heading_candidates(text: str, limit: int) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not _looks_like_heading(line):
            continue
        if line in seen:
            continue
        seen.add(line)
        candidates.append(line)
        if len(candidates) >= limit:
            break
    return candidates


def _looks_like_heading(line: str) -> bool:
    if not line:
        return False
    if len(line) > 80:
        return False
    for pattern in HEADING_PATTERNS:
        if pattern.match(line):
            return True
    return False


def _nodes_from_generation_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(result.get("items"), list):
        return _nodes_from_toc_items(result["items"])
    raise ValueError("目录 JSON 缺少 items[]。")


def _summary_from_generation_result(result: dict[str, Any]) -> str:
    summary = result.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    if isinstance(summary, dict):
        total_items = summary.get("total_items")
        annotation_counts = summary.get("annotation_counts") or {}
        if isinstance(annotation_counts, dict) and annotation_counts:
            counts = "，".join(
                f"{key}{value}"
                for key, value in annotation_counts.items()
                if value
            )
            if counts:
                return f"目录生成完成，共 {total_items or 0} 条目录项（{counts}）。"
        return f"目录生成完成，共 {total_items or 0} 条目录项。"
    return "目录生成完成。"


def _nodes_from_toc_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []
    counters: list[int] = []

    for fallback_order, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        level = _coerce_toc_level(item.get("level"))
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
        node_id = "OL-" + "-".join(str(part) for part in counters[:level] if part)

        title = _toc_item_title(item, fallback_order)
        node = {
            "id": node_id,
            "title": title,
            "children": [],
            "tocNumber": str(item.get("number") or "").strip(),
            "annotation": str(item.get("annotation") or "").strip(),
            "source": str(item.get("source") or "").strip(),
            "reason": str(item.get("reason") or "").strip(),
        }
        if isinstance(item.get("source_refs"), list):
            node["sourceRefs"] = item["source_refs"]
        if isinstance(item.get("material_refs"), list):
            node["materialRefs"] = item["material_refs"]
        if stack:
            stack[-1][1].setdefault("children", []).append(node)
        else:
            roots.append(node)
        stack.append((level, node))

    return roots


def _coerce_toc_level(value: Any) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        level = 1
    return max(1, min(level, max(1, settings.s2_toc_max_level)))


def _toc_item_title(item: dict[str, Any], fallback_order: int) -> str:
    title = str(item.get("title") or "").strip()
    number = str(item.get("number") or "").strip()
    if title:
        if number and not re.fullmatch(r"\d+(?:\.\d+)*", number):
            return f"{number} {title}".strip()
        return title
    if number:
        return number
    return f"未命名章节{fallback_order}"
