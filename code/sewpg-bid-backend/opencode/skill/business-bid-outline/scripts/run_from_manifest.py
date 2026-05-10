from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from prepare_history_bid_outline_inputs import build_output as build_history_outline_inputs
from prepare_tender_map_inputs import (
    build_checklist_hits,
    build_inputs as build_tender_inputs,
    build_zones,
    parse_checklist,
)


WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CHINESE_NUMERAL = "[一二三四五六七八九十百千万零〇两]+"
HEADING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"^第(?P<num>{CHINESE_NUMERAL}|\d+)章[\s　:：、.-]*(?P<title>.+)$"),
    re.compile(r"^(?P<num>\d+(?:\.\d+)*)(?:[\s　:：、.-]+)(?P<title>.+)$"),
    re.compile(rf"^(?P<num>{CHINESE_NUMERAL})[、.．]\s*(?P<title>.+)$"),
    re.compile(r"^[（(](?P<num>\d+)[）)]\s*(?P<title>.+)$"),
)
REQUIREMENT_PATTERN = re.compile(r"(?:投标人|供应商|响应方|报价人|申请人)?(?:应|须|必须|需|需要|应当|提供|提交|编制|说明|承诺|响应)(?P<title>[^。；;\n]{2,90})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate business bid outline from backend manifest.")
    parser.add_argument("manifest", nargs="?")
    parser.add_argument("--manifest", dest="manifest_option")
    parser.add_argument("--response", choices=("summary", "review"), default="summary")
    args = parser.parse_args()

    manifest_path = Path(str(args.manifest_option or args.manifest or "")).expanduser()
    if not manifest_path.exists():
        raise SystemExit(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = run_manifest(manifest, manifest_path)
    response = result["review"] if args.response == "review" else result["summary"]
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


def run_manifest(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    work_dir = Path(str(manifest.get("workDir") or manifest_path.parent)).expanduser()
    work_dir.mkdir(parents=True, exist_ok=True)
    history_inputs_file = work_dir / "history_bid_outline_inputs.json"
    tender_map_inputs_file = work_dir / "tender_map_inputs.json"
    outline_file = work_dir / "outline.json"

    template_file = existing_path(manifest.get("templateFile"), "templateFile")
    tender_files = tender_inputs(manifest)
    if not tender_files:
        raise SystemExit("tenderFiles has no usable docx entries")

    history_inputs = build_history_outline_inputs(template_file)
    history_inputs_file.write_text(json.dumps(history_inputs, ensure_ascii=False, indent=2), encoding="utf-8")
    template_outline = history_candidates_for_toc(history_inputs)
    if not template_outline:
        raise SystemExit("templateFile has no usable outline entries")

    tender_map_inputs = build_tender_map_inputs(tender_files[0], work_dir)
    tender_map_inputs_file.write_text(json.dumps(tender_map_inputs, ensure_ascii=False, indent=2), encoding="utf-8")
    candidates = extract_candidates_from_tender_map(tender_map_inputs, tender_files[0])
    outline_payload = build_fallback_outline(
        manifest=manifest,
        history_inputs=history_inputs,
        template_outline=template_outline,
        tender_candidates=candidates,
    )
    outline_file.write_text(json.dumps(outline_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "schema_version": "business-outline-inputs-v1",
        "skill": "business-bid-outline",
        "businessOutlineFile": str(outline_file),
        "tenderMapInputsFile": str(tender_map_inputs_file),
        "historyBidOutlineInputsFile": str(history_inputs_file),
        "summary": {
            "history_outline_candidate_count": len(template_outline),
            "tender_candidate_count": len(candidates),
            "outline_section_count": len(outline_payload.get("sections") or []),
            "tender_file_count": len(tender_files),
        },
    }
    return {"summary": summary, "review": summary}


def build_fallback_outline(
    *,
    manifest: dict[str, Any],
    history_inputs: dict[str, Any],
    template_outline: list[dict[str, Any]],
    tender_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    sections = outline_sections_from_template(template_outline, tender_candidates)
    if not sections:
        sections = outline_sections_from_tender_candidates(tender_candidates)
    if not sections:
        sections = [
            {
                "id": "BIZ-FALLBACK-001",
                "title": "商务响应文件",
                "number": None,
                "level": 1,
                "required_status": "待确认",
                "source_text": "本目录由 business-bid-outline 本地兜底生成，请人工确认商务标目录结构。",
                "source_refs": [],
                "reason": "历史商务标模板和招标文件未解析出明确目录项，生成兜底父节点供人工审核。",
                "children": [],
            }
        ]
    return {
        "schema_version": "business_bid_outline.v1",
        "document_name": str(manifest.get("projectName") or history_inputs.get("document_name") or "商务标目录"),
        "outline_source": {
            "section_title": "本地兜底商务标目录",
            "source_text": str((template_outline[0] if template_outline else {}).get("rawText") or "local runner fallback"),
            "confidence": "low",
            "source_type": "local_runner_fallback",
            "history_document_name": str(history_inputs.get("document_name") or ""),
            "summary": "futurecode 不可用或超时时，由本地 runner 基于历史商务标目录候选生成待审核目录。",
        },
        "context": {
            "fallback": {
                "summary": "futurecode 不可用或超时时触发本地兜底目录，后续需要人工审核。",
                "source_text": str((template_outline[0] if template_outline else {}).get("rawText") or "local runner fallback"),
            }
        },
        "sections": sections,
        "review_items": [
            {
                "id": "REVIEW-FALLBACK-001",
                "message": "本目录为本地兜底结果，需要人工审核后再进入后续阶段。",
                "source_text": "futurecode 不可用或超时时触发本地兜底目录。",
                "suggested_section_id": None,
                "required_status": "待确认",
                "severity": "warning",
            }
        ],
    }


def outline_sections_from_template(
    template_outline: list[dict[str, Any]],
    tender_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for index, item in enumerate(template_outline, start=1):
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        level = max(1, min(int(item.get("level") or 1), 6))
        candidate = first_matching_candidate(title, tender_candidates)
        raw_text = str((candidate or {}).get("rawText") or item.get("rawText") or title)
        section = {
            "id": f"BIZ-FALLBACK-{index:04d}",
            "title": title,
            "number": section_number(item.get("number")),
            "level": level,
            "required_status": "必要" if candidate else "待确认",
            "source_text": raw_text,
            "source_refs": [source_ref(candidate)] if candidate else [],
            "reason": "本地兜底继承历史商务标目录；当前招标依据需人工复核。" if not candidate else "本地兜底继承历史商务标目录，并匹配到当前招标文件候选依据。",
            "children": [],
        }
        while stack and int(stack[-1].get("level") or 1) >= level:
            stack.pop()
        if stack:
            stack[-1].setdefault("children", []).append(section)
        else:
            roots.append(section)
        stack.append(section)
    return roots


def outline_sections_from_tender_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates[:40], start=1):
        title = str(candidate.get("title") or "").strip()
        if not title:
            continue
        sections.append(
            {
                "id": f"BIZ-TENDER-{index:04d}",
                "title": title,
                "number": None,
                "level": 1,
                "required_status": "待确认",
                "source_text": str(candidate.get("rawText") or title),
                "source_refs": [source_ref(candidate)],
                "reason": "历史商务标目录不可用时，由招标文件要求候选生成，需人工确认。",
                "children": [],
            }
        )
    return sections


def existing_path(value: Any, field: str) -> Path:
    path = Path(str(value or "")).expanduser()
    if not path.exists():
        raise SystemExit(f"{field} not found: {path}")
    return path


def tender_inputs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    records = manifest.get("tenderFiles") if isinstance(manifest.get("tenderFiles"), list) else []
    result: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            continue
        path = Path(str(record.get("path") or "")).expanduser()
        if not path.exists():
            continue
        result.append(
            {
                "id": str(record.get("id") or f"tender-{index}"),
                "name": str(record.get("name") or path.name),
                "path": path,
            }
        )
    return result


def source_file_payload(item: dict[str, Any]) -> dict[str, str]:
    return {"id": str(item.get("id") or ""), "name": str(item.get("name") or ""), "path": str(item.get("path") or "")}


def section_number(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def history_candidates_for_toc(history_inputs: dict[str, Any]) -> list[dict[str, Any]]:
    document_name = str(history_inputs.get("document_name") or "")
    candidates = history_inputs.get("outline_candidates") if isinstance(history_inputs.get("outline_candidates"), list) else []
    result: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        title = str(candidate.get("title_hint") or "").strip()
        if not title:
            continue
        result.append(
            {
                "number": section_number(candidate.get("number")),
                "title": title,
                "level": max(1, int(candidate.get("level") or 1)),
                "sourceFile": document_name,
                "paragraphIndex": index,
                "rawText": str(candidate.get("source_text") or title),
                "sourceType": str(candidate.get("source_type") or "history_bid"),
            }
        )
    return result


def build_tender_map_inputs(file_record: dict[str, Any], work_dir: Path) -> dict[str, Any]:
    checklist_path = SCRIPT_DIR.parent / "references" / "expert-checklist.md"
    checklist = parse_checklist(checklist_path)
    blocks, tables = build_tender_inputs(Path(str(file_record.get("path") or "")), checklist)
    zones = build_zones(blocks, tables, checklist)
    return {
        "document_name": str(file_record.get("name") or Path(str(file_record.get("path") or "")).name),
        "source_path": str(file_record.get("path") or ""),
        "work_dir": str(work_dir),
        "blocks": blocks,
        "tables": tables,
        "zones": zones,
        "expert_checklist_hits": build_checklist_hits(blocks, tables, zones, checklist),
    }


def extract_candidates_from_tender_map(tender_map_inputs: dict[str, Any], file_record: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    blocks = tender_map_inputs.get("blocks") if isinstance(tender_map_inputs.get("blocks"), list) else []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        match = REQUIREMENT_PATTERN.search(text)
        if not match:
            continue
        title = normalize_candidate_title(match.group("title"))
        key = title_key(title)
        if not key or key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "id": f"BUS-CAND-{len(candidates) + 1:04d}",
                "title": title,
                "rawText": text,
                "sourceFile": str(file_record.get("path") or ""),
                "fileId": str(file_record.get("id") or ""),
                "fileName": str(file_record.get("name") or Path(str(file_record.get("path") or "")).name),
                "paragraphIndex": block.get("paragraph_index"),
                "blockId": block.get("block_id"),
                "kind": "business_requirement",
            }
        )
    return candidates


def first_matching_candidate(title: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    key = title_key(title)
    if not key:
        return None
    for candidate in candidates:
        candidate_key = title_key(str(candidate.get("title") or ""))
        if candidate_key and (key in candidate_key or candidate_key in key):
            return candidate
    return None


def extract_outline(path: Path) -> list[dict[str, Any]]:
    paragraphs = docx_paragraphs(path)
    outline: list[dict[str, Any]] = []
    for index, paragraph in enumerate(paragraphs):
        text = paragraph.strip()
        if not text:
            continue
        parsed = parse_heading(text)
        if parsed is None:
            continue
        number, title, level = parsed
        outline.append(
            {
                "number": number,
                "title": title,
                "level": level,
                "sourceFile": path.name,
                "paragraphIndex": index,
                "rawText": text,
            }
        )
    return outline


def docx_paragraphs(path: Path) -> list[str]:
    if path.suffix.lower() != ".docx":
        return []
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{WORD_NS}p"):
        texts = [node.text or "" for node in paragraph.iter(f"{WORD_NS}t")]
        paragraphs.append("".join(texts).strip())
    return paragraphs


def parse_heading(text: str) -> tuple[str, str, int] | None:
    for pattern in HEADING_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        number = str(match.group("num") or "").strip()
        title = str(match.group("title") or "").strip()
        level = 1 if text.startswith("第") else min(number.count(".") + 1, 4)
        if title:
            return number, title, level
    return None


def extract_candidates(tender_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for file_record in tender_files:
        path = Path(str(file_record.get("path") or ""))
        for index, paragraph in enumerate(docx_paragraphs(path)):
            text = paragraph.strip()
            if not text:
                continue
            match = REQUIREMENT_PATTERN.search(text)
            if not match:
                continue
            title = normalize_candidate_title(match.group("title"))
            key = title_key(title)
            if not key or key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "id": f"BUS-CAND-{len(candidates) + 1:04d}",
                    "title": title,
                    "rawText": text,
                    "sourceFile": path.name,
                    "fileId": str(file_record.get("id") or ""),
                    "fileName": str(file_record.get("name") or path.name),
                    "paragraphIndex": index,
                    "kind": "business_requirement",
                }
            )
    return candidates


def normalize_candidate_title(value: str) -> str:
    text = re.sub(r"[，,。；;：:].*$", "", str(value or "")).strip()
    text = re.sub(r"^(?:相关|相应|有关)", "", text).strip()
    return text[:60]


def source_ref(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "fileId": str(candidate.get("fileId") or ""),
        "fileName": str(candidate.get("fileName") or candidate.get("sourceFile") or ""),
        "paragraphIndex": candidate.get("paragraphIndex"),
        "searchText": str(candidate.get("rawText") or candidate.get("title") or ""),
        "reason": "商务标招标要求依据",
    }


def title_key(value: str) -> str:
    text = re.sub(r"\s+", "", str(value or "").lower())
    text = re.sub(r"[，,。.:：;；、（）()\[\]【】《》<>\"'“”‘’\\/_-]+", "", text)
    return text


if __name__ == "__main__":
    raise SystemExit(main())
