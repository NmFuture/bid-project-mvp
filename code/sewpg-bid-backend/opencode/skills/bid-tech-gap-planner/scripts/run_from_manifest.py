#!/usr/bin/env python3
"""Build bid-tech-gap-plan-v1 from confirmed TOC and parse artifacts."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = "bid-tech-gap-plan-v1"
APPENDIX_CODE_RE = re.compile(
    r"附表\s*([A-Za-z]?\s*\.?\s*\d+(?:\.\d+)*)(?:\s*[-—~～至到]\s*([A-Za-z]?\s*\.?\s*\d+(?:\.\d+)*))?",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"JSON must be an object: {path}")
    return data


def toc_items(toc: dict[str, Any]) -> list[dict[str, Any]]:
    items = toc.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def appendices_from_parse(parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    structured = parse_result.get("structured") if isinstance(parse_result.get("structured"), dict) else {}
    appendices = structured.get("appendices")
    if isinstance(appendices, list):
        return [item for item in appendices if isinstance(item, dict)]
    items = structured.get("items") or parse_result.get("items") or []
    result: list[dict[str, Any]] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            text = " ".join(str(item.get(key) or "") for key in ("category", "title", "keyEntity", "keyValue"))
            if "附表" in text or "空表" in text:
                result.append(item)
    return result


def parse_fields_from_parse(parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = parse_result.get("items")
    structured = parse_result.get("structured") if isinstance(parse_result.get("structured"), dict) else {}
    if not isinstance(raw_items, list):
        raw_items = structured.get("items") if isinstance(structured.get("items"), list) else []
    allowed_types = {"项目基础信息", "风机核心参数", "性能保证指标", "环境适应性要求", "环境适应性"}
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    priority_terms = (
        "标段规模",
        "总装机容量",
        "总容量",
        "机组数量",
        "机组台数",
        "风机数量",
        "单机容量",
        "空气密度",
        "湍流强度",
        "风剪切",
        "年平均风速",
        "参考风速",
        "极端风速",
    )
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or item.get("category") or "")
        if allowed_types and item_type and item_type not in allowed_types:
            continue
        label = str(item.get("keyEntity") or item.get("title") or item.get("label") or item.get("fieldKey") or "").strip()
        value = str(item.get("keyValue") or item.get("value") or "").strip()
        if not label or not value or len(value) > 240:
            continue
        key = f"{label}::{value}"
        if key in seen:
            continue
        seen.add(key)
        value_text = str(value)
        evidence = str(item.get("evidence") or "")
        evidence_location = str(item.get("evidenceLocation") or "")
        priority = 0
        if any(term in label for term in priority_terms):
            priority += 100
        if re.search(r"\d+(?:\.\d+)?\s*(MW|kW|万千瓦|kg/?m[³3]|台|m/s|%)", value_text + " " + evidence, flags=re.I):
            priority += 30
        if evidence_location.startswith("B"):
            priority += 20
        if len(value_text) > 120:
            priority -= 15
        fields.append(
            {
                "id": str(item.get("id") or item.get("fieldKey") or label),
                "label": label,
                "value": value,
                "sourceFile": str(item.get("sourceFile") or ""),
                "evidence": evidence,
                "evidenceLocation": evidence_location,
                "_priority": priority,
            }
        )
    fields.sort(key=lambda field: (field.get("_priority") or 0, field.get("id") or ""), reverse=True)
    for field in fields:
        field.pop("_priority", None)
    return fields[:320]


def wiki_cards_by_section(wiki_dir: Path | None) -> dict[str, list[dict[str, Any]]]:
    if not wiki_dir or not (wiki_dir / "卡片").exists():
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    for path in sorted((wiki_dir / "卡片").rglob("*.md")):
        fields = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        if not fields or str(fields.get("deprecated") or "").lower() == "true":
            continue
        section = str(fields.get("skeleton_section") or "").strip()
        if not section:
            continue
        result.setdefault(section, []).append(
            {
                "id": str(fields.get("material_id") or fields.get("id") or fields.get("path") or path.stem),
                "path": str(fields.get("path") or ""),
                "name": str(fields.get("name") or path.stem),
                "scope": str(fields.get("scope") or ""),
                "category": str(fields.get("category") or ""),
                "source": "wiki",
                "matchReason": f"Wiki 卡片 skeleton_section={section}",
                "confidence": 0.82,
            }
        )
    return result


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fields: dict[str, str] = {}
    for raw_line in text[3:end].strip().splitlines():
        if ":" not in raw_line:
            continue
        key, _, value = raw_line.partition(":")
        fields[key.strip()] = clean_value(value)
    return fields


def clean_value(value: str) -> str:
    text = str(value or "").strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1]
    return text


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return re.sub(r"\s+", " ", str(value).replace("\n", " / ")).strip()


def normalize_key(value: Any) -> str:
    return re.sub(r"[\s　,，、.。:：;；()（）\[\]【】{}<>《》\"'`·_\-—/\\|]+", "", str(value or "").lower())


def source_terms(value: Any) -> list[str]:
    if isinstance(value, list):
        terms: list[str] = []
        seen: set[str] = set()
        for item in value:
            for term in source_terms(item):
                if term and term not in seen:
                    seen.add(term)
                    terms.append(term)
        return terms
    text = clean_text(value)
    if not text:
        return []
    terms: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[&＆,，、;；/／\n]+", text):
        term = clean_text(raw).strip(" ：:")
        if not term or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def normalize_appendix_code(value: Any) -> str:
    return re.sub(r"\s+", "", clean_text(value).upper()).lstrip(".")


def toc_number_key(number: Any) -> str:
    text = str(number or "").strip()
    chapter_match = re.fullmatch(r"第\s*([一二三四五六七八九十百千万0-9]+)\s*章", text)
    if chapter_match:
        value = chinese_number_to_int(chapter_match.group(1))
        return str(value) if value is not None else text
    return text


def chinese_number_to_int(value: str) -> int | None:
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    digits = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if text in digits:
        return digits[text]
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    return None


def appendix_code(value: Any) -> str:
    match = APPENDIX_CODE_RE.search(str(value or "").strip())
    return normalize_appendix_code(match.group(1)) if match else ""


def _appendix_code_parts(value: Any) -> tuple[str, tuple[int, ...]] | None:
    code = normalize_appendix_code(value)
    match = re.fullmatch(r"([A-Z]+)?\.?([0-9]+(?:\.[0-9]+)*)", code)
    if not match:
        return None
    prefix = match.group(1) or ""
    numbers = tuple(int(part) for part in match.group(2).split("."))
    return prefix, numbers


def appendix_rule_code_score(table_title: Any, rule_title: Any) -> float:
    table_code = appendix_code(table_title)
    if not table_code:
        return 0.0
    rule_match = APPENDIX_CODE_RE.search(clean_text(rule_title))
    if not rule_match:
        return 0.0
    start_code = normalize_appendix_code(rule_match.group(1))
    end_code = normalize_appendix_code(rule_match.group(2) or "")
    if not end_code:
        return 0.96 if table_code == start_code else 0.0

    table_parts = _appendix_code_parts(table_code)
    start_parts = _appendix_code_parts(start_code)
    end_parts = _appendix_code_parts(end_code)
    if not table_parts or not start_parts or not end_parts:
        return 0.0
    table_prefix, table_numbers = table_parts
    start_prefix, start_numbers = start_parts
    end_prefix, end_numbers = end_parts
    if not end_prefix:
        end_prefix = start_prefix
    if table_prefix and start_prefix and table_prefix != start_prefix:
        return 0.0
    if table_prefix and end_prefix and table_prefix != end_prefix:
        return 0.0
    if start_numbers <= table_numbers <= end_numbers:
        return 0.94
    return 0.0


def is_structural(item: dict[str, Any], all_items: list[dict[str, Any]]) -> bool:
    level = int(item.get("level") or 0)
    number = str(item.get("number") or "").strip()
    if not number:
        return False
    prefix = number + "."
    return any(str(other.get("number") or "").startswith(prefix) for other in all_items) or level == 1


def normalize_material_refs(item: dict[str, Any]) -> list[dict[str, Any]]:
    refs = item.get("material_refs") or item.get("materialRefs") or []
    output: list[dict[str, Any]] = []
    if not isinstance(refs, list):
        return output
    for index, ref in enumerate(refs, start=1):
        if isinstance(ref, str):
            output.append(
                {
                    "id": ref,
                    "name": PurePosixPath(ref).name or ref,
                    "path": ref,
                    "usage": "section_merge",
                    "matchReason": "目录生成已引用素材",
                    "confidence": 0.85,
                    "source": "toc",
                }
            )
            continue
        if not isinstance(ref, dict):
            continue
        path = str(ref.get("docx") or ref.get("path") or ref.get("cleanedPath") or "")
        name = str(ref.get("name") or ref.get("fileName") or ref.get("cleanedFileName") or PurePosixPath(path).name or "")
        folder_path = str(ref.get("folderPath") or "")
        if not folder_path and "/" in path:
            folder_path = str(PurePosixPath(path).parent)
        output.append(
            {
                "id": str(ref.get("id") or ref.get("material_id") or f"MAT-{index}"),
                "name": name,
                "path": path,
                "folderPath": folder_path,
                "materialTier": str(ref.get("materialTier") or ref.get("materialScope") or ""),
                "cleanedFileName": str(ref.get("cleanedFileName") or ""),
                "hasCleanedWord": bool(ref.get("hasCleanedWord") or ref.get("cleanedFileName")),
                "usage": str(ref.get("usage") or "section_merge"),
                "matchReason": str(ref.get("reason") or "目录生成已引用素材"),
                "confidence": float(ref.get("confidence") or 0.85),
                "source": "toc",
            }
        )
    return output


def material_index_from_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = manifest.get("materialIndex") or manifest.get("materials") or []
    output: list[dict[str, Any]] = []
    if not isinstance(raw_items, list):
        return output
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("fileName") or raw.get("cleanedFileName") or "")
        folder_path = str(raw.get("folderPath") or "")
        evidence_segments = raw.get("evidenceSegments")
        output.append(
            {
                "id": str(raw.get("id") or raw.get("materialId") or ""),
                "name": name,
                "path": str(raw.get("path") or (f"{folder_path}/{name}" if folder_path and name else "")),
                "folderPath": folder_path,
                "materialTier": str(raw.get("materialTier") or ""),
                "cleanedFileName": str(raw.get("cleanedFileName") or ""),
                "hasCleanedWord": bool(raw.get("hasCleanedWord") or raw.get("cleanedFileName")),
                "requiresFill": bool(raw.get("requiresFill")),
                "placeholderCount": int(raw.get("placeholderCount") or 0),
                "placeholderLabels": list(raw.get("placeholderLabels") or []),
                "placeholderSamples": list(raw.get("placeholderSamples") or []),
                "fillProfile": raw.get("fillProfile") if isinstance(raw.get("fillProfile"), dict) else {},
                "evidenceSegments": list(evidence_segments) if isinstance(evidence_segments, list) else [],
                "usage": "section_merge",
                "matchReason": "允许素材范围内的素材索引候选",
                "confidence": 0.74,
                "source": "material_index",
                "turbineModelLabel": str(raw.get("turbineModelLabel") or ""),
            }
        )
    return output


def material_scope_paths(manifest: dict[str, Any]) -> list[str]:
    scope = manifest.get("materialScope") if isinstance(manifest.get("materialScope"), dict) else {}
    raw_paths = scope.get("paths")
    if not isinstance(raw_paths, list):
        raw_paths = [
            item.get("path")
            for item in scope.get("readableScopes") or []
            if isinstance(item, dict)
        ]
    return [
        normalize_key(path)
        for path in raw_paths
        if normalize_key(path)
    ]


def material_within_scope(material: dict[str, Any], allowed_paths: list[str]) -> bool:
    if not allowed_paths:
        return True
    text = normalize_key(
        " ".join(
            str(material.get(key) or "")
            for key in ("path", "docx", "folderPath", "cleanedPath")
        )
    )
    if not text:
        return False
    return any(text.startswith(path) or path in text for path in allowed_paths)


def material_lookup_keys(material: dict[str, Any]) -> list[str]:
    values = [
        material.get("id"),
        material.get("materialId"),
        material.get("path"),
        material.get("docx"),
        material.get("cleanedPath"),
        material.get("cleanedFileName"),
        material.get("name"),
    ]
    path = str(material.get("path") or material.get("docx") or "").strip()
    if path:
        values.append(PurePosixPath(path).name)
    return [normalize_key(value) for value in values if normalize_key(value)]


def material_path_key(material: dict[str, Any]) -> str:
    return normalize_key(
        material.get("path")
        or material.get("docx")
        or (
            f"{material.get('folderPath')}/{material.get('name')}"
            if material.get("folderPath") and material.get("name")
            else ""
        )
    )


def merge_hint_with_index_material(hint: dict[str, Any], indexed: dict[str, Any]) -> dict[str, Any]:
    material = dict(indexed)
    for key in ("usage", "matchReason", "confidence", "source"):
        if hint.get(key):
            material[key] = hint[key]
    if not material.get("path") and hint.get("path"):
        material["path"] = hint["path"]
    return material


def resolve_material_hints(
    hints: list[dict[str, Any]],
    indexed_materials: list[dict[str, Any]],
    allowed_paths: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Resolve TOC/Wiki hints against the manifest's allowed material index.

    In production the backend pre-filters materialIndex by project, customer,
    bid type, and turbine model. A TOC/Wiki reference is therefore only usable
    when it can be resolved back into that allowed index. Unit tests and
    offline fixtures may provide no materialIndex, so the hints remain usable
    as a deterministic fallback there.
    """

    if not indexed_materials:
        return dedupe_materials(
            [hint for hint in hints if material_within_scope(hint, allowed_paths or [])]
        )

    by_key: dict[str, dict[str, Any]] = {}
    by_path: dict[str, dict[str, Any]] = {}
    for material in indexed_materials:
        for key in material_lookup_keys(material):
            by_key.setdefault(key, material)
        path_key = material_path_key(material)
        if path_key:
            by_path.setdefault(path_key, material)

    resolved: list[dict[str, Any]] = []
    for hint in hints:
        match: dict[str, Any] | None = None
        for key in material_lookup_keys(hint):
            match = by_key.get(key)
            if match:
                break
        if not match:
            hint_path = material_path_key(hint)
            match = by_path.get(hint_path) if hint_path else None
        if not match:
            hint_name = normalize_key(hint.get("name") or PurePosixPath(str(hint.get("path") or "")).name)
            if hint_name:
                match = next(
                    (
                        material
                        for material in indexed_materials
                        if hint_name in normalize_key(material_text(material))
                    ),
                    None,
                )
        if match:
            resolved.append(merge_hint_with_index_material(hint, match))
        elif material_within_scope(hint, allowed_paths or []):
            resolved.append(hint)
    return dedupe_materials(resolved)


def dedupe_materials(materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for material in materials:
        if not isinstance(material, dict):
            continue
        key = str(material.get("id") or material.get("path") or material.get("name") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(material)
    return output


def material_text(material: dict[str, Any]) -> str:
    return " ".join(
        str(material.get(key) or "")
        for key in ("name", "path", "docx", "cleanedPath", "folderPath", "cleanedFileName", "matchReason")
    )


def material_file_text(material: dict[str, Any]) -> str:
    path = str(material.get("path") or material.get("docx") or "").strip()
    return " ".join(
        str(value or "")
        for value in (
            material.get("name"),
            material.get("cleanedFileName"),
            PurePosixPath(path).name if path else "",
        )
    )


def material_requires_fill(material: dict[str, Any] | None) -> bool:
    if not material:
        return False
    if bool(material.get("requiresFill")):
        return True
    if int(material.get("placeholderCount") or 0) > 0:
        return True
    text = material_text(material)
    return any(marker in text for marker in ("待填写", "待补充", "待确认"))


def material_score(material: dict[str, Any], title: str) -> float:
    text = normalize_key(material_text(material))
    title_key = normalize_key(title)
    score = float(material.get("confidence") or 0) * 10
    if title_key and title_key in text:
        score += 120
    for token in re.split(r"[与及和、/\\（）()]+", str(title or "")):
        token_key = normalize_key(token)
        if len(token_key) >= 2 and token_key in text:
            score += 16
    tier = str(material.get("materialTier") or "").lower()
    if tier == "project":
        score += 20
    elif tier == "customer":
        score += 12
    elif tier == "standard":
        score += 5
    if str(material.get("hasCleanedWord") or "").lower() == "true" or material.get("cleanedFileName"):
        score += 6
    return score


def _segment_text(segment: dict[str, Any]) -> str:
    """证据片段的可匹配文本：标题 + 摘要 + 关键词。"""
    keywords = segment.get("keywords") if isinstance(segment.get("keywords"), list) else []
    return " ".join(
        str(value or "")
        for value in (segment.get("title"), segment.get("summary"), " ".join(str(k) for k in keywords))
    )


def segment_score(segment: dict[str, Any], title: str) -> float:
    """单个证据片段相对目录标题的相关度打分（纯算法，无 LLM）。

    维度（中文无空格分词，故同时用整串子串和片段自带 keywords 双向命中）：
    - 标题整串命中片段标题/正文：强信号。
    - title_terms 分词命中：词面信号。
    - 片段 keywords 与标题的双向子串命中：中文场景的主力信号
      （A 层已把领域词如「混塔」「电网友好性」切进 keywords，弥补 title_terms 不切中文词）。
    返回非负分，0 表示无任何重合。
    """
    seg_title = normalize_key(segment.get("title"))
    seg_text = normalize_key(_segment_text(segment))
    title_key = normalize_key(title)
    if not seg_text or not title_key:
        return 0.0
    score = 0.0
    if title_key in seg_title:
        score += 60
    elif title_key in seg_text:
        score += 30
    for term in title_terms(title):
        if term in seg_title:
            score += 20
        elif term in seg_text:
            score += 8
    # 片段关键词双向命中：keyword 出现在标题里，或标题里的关键词出现在 keyword 里。
    keywords = segment.get("keywords") if isinstance(segment.get("keywords"), list) else []
    for keyword in keywords:
        key = normalize_key(keyword)
        if len(key) < 2:
            continue
        if key in title_key or title_key in key:
            score += 24
    return score


def recall_material_segments(material: dict[str, Any], title: str, *, limit: int = 3) -> list[dict[str, Any]]:
    """从一份素材的 evidenceSegments 里召回与目录标题最相关的片段。

    仅返回有正向相关度（score > 0）的片段，按分降序取前 limit 条；素材没有片段
    或全不相关时返回空（调用方退化为文件级匹配）。每条附 matchScore 便于前端展示。
    """
    segments = material.get("evidenceSegments")
    if not isinstance(segments, list) or not segments:
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        score = segment_score(segment, title)
        if score > 0:
            enriched = dict(segment)
            enriched["matchScore"] = round(score, 2)
            scored.append((score, enriched))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [segment for _, segment in scored[:limit]]


def attach_recalled_segments(materials: list[dict[str, Any]], title: str, *, limit: int = 3) -> list[dict[str, Any]]:
    """给候选素材附上「与本目录标题相关的证据片段」+ 综合 matchScore。

    用于非附表正文缺口：在文件级匹配之上叠加段落级证据，让下游 AI/人工能定位到
    素材内具体段落。matchScore = 文件级 material_score + 最佳片段分，便于排序与展示。
    不改动来源矩阵/附表路径。
    """
    enriched_list: list[dict[str, Any]] = []
    for material in materials:
        if not isinstance(material, dict):
            continue
        recalled = recall_material_segments(material, title, limit=limit)
        item = dict(material)
        base = material_score(material, title)
        best_segment = recalled[0]["matchScore"] if recalled else 0.0
        item["matchScore"] = round(base + best_segment, 2)
        if recalled:
            item["recalledSegments"] = recalled
            item["matchReason"] = f"段落级证据召回（{len(recalled)} 段相关）"
        enriched_list.append(item)
    return enriched_list


def title_terms(title: str) -> list[str]:
    text = re.sub(r"附表\s*[A-Za-z]?\s*\.?\s*\d+(?:\.\d+)*", " ", str(title or ""))
    text = re.sub(r"第\s*[一二三四五六七八九十百千万0-9]+\s*章", " ", text)
    text = re.sub(r"\b\d+(?:\.\d+)*\b", " ", text)
    parts = re.split(r"[\s　,，、.。:：;；()（）\[\]【】{}<>《》\"'`·_\-—/\\|与及和]+", text)
    stop_words = {"", "目录", "章节", "内容", "说明", "要求", "材料", "文件", "技术标", "投标文件"}
    prefixes = ("投标人", "投标方", "投标", "本项目", "项目", "技术标")
    terms: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = normalize_key(part)
        for prefix in prefixes:
            prefix_key = normalize_key(prefix)
            if key.startswith(prefix_key) and len(key) - len(prefix_key) >= 2:
                key = key[len(prefix_key):]
                break
        if len(key) < 2 or key in stop_words or key in seen:
            continue
        seen.add(key)
        terms.append(key)
    return terms


def chapter_title_matches_file(material: dict[str, Any], title: str) -> bool:
    file_text = normalize_key(material_file_text(material))
    title_key = normalize_key(title)
    if not file_text or not title_key:
        return False
    if title_key in file_text:
        return True
    terms = title_terms(title)
    if len(terms) < 2:
        return False
    matched_terms = sum(1 for term in terms if term in file_text)
    return matched_terms == len(terms)


def chapter_master_score(material: dict[str, Any], title: str, child_titles: list[str] | None = None) -> float:
    score = material_score(material, title)
    text = normalize_key(material_text(material))
    file_text = normalize_key(material_file_text(material))
    title_key = normalize_key(title)
    if title_key and title_key in file_text:
        score += 520
    elif chapter_title_matches_file(material, title):
        score += 430
    elif title_key and title_key in text:
        score += 180
    for term in title_terms(title):
        if term in file_text:
            score += 58
        elif term in text:
            score += 22
    child_matches = 0
    for child_title in child_titles or []:
        child_key = normalize_key(child_title)
        if child_key and len(child_key) >= 3 and child_key in text:
            child_matches += 1
    score += child_matches * 70
    if str(material.get("materialTier") or "").lower() == "project":
        score += 30
    if str(material.get("materialTier") or "").lower() == "standard":
        score += 12
    return score


def pick_material(candidates: list[dict[str, Any]], title: str, *, usage: str = "section_merge") -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    materials = dedupe_materials(candidates)
    if not materials:
        return None, []
    ranked = sorted(materials, key=lambda material: material_score(material, title), reverse=True)
    selected = dict(ranked[0])
    selected["usage"] = usage
    alternatives = [dict(item) for item in ranked[1:]]
    return selected, alternatives


def pick_chapter_master_material(
    candidates: list[dict[str, Any]],
    title: str,
    child_titles: list[str] | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    materials = dedupe_materials(candidates)
    if not materials:
        return None, []
    ranked = sorted(
        materials,
        key=lambda material: chapter_master_score(material, title, child_titles),
        reverse=True,
    )
    selected = dict(ranked[0])
    selected["usage"] = "chapter_master"
    selected["matchReason"] = f"整章素材覆盖“{title}”及其子节。"
    alternatives = [dict(item) for item in ranked[1:]]
    return selected, alternatives


def matching_materials_for_title(materials: list[dict[str, Any]], title: str) -> list[dict[str, Any]]:
    title_key = normalize_key(title)
    if not title_key:
        return []
    return [
        material
        for material in materials
        if title_key in normalize_key(material_text(material))
    ]


def chapter_children(item: dict[str, Any], all_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    number_key = toc_number_key(item.get("number"))
    if not number_key or "." in number_key:
        return []
    prefix = f"{number_key}."
    return [
        other
        for other in all_items
        if str(toc_number_key(other.get("number"))).startswith(prefix)
    ]


def chapter_master_candidates(materials: list[dict[str, Any]], title: str) -> list[dict[str, Any]]:
    title_key = normalize_key(title)
    if not title_key:
        return []
    result: list[dict[str, Any]] = []
    for material in materials:
        text = normalize_key(material_text(material))
        if title_key and title_key in text:
            result.append(material)
    return result


def strong_chapter_master_candidates(
    materials: list[dict[str, Any]],
    title: str,
    child_titles: list[str],
) -> list[dict[str, Any]]:
    title_key = normalize_key(title)
    child_keys = [
        normalize_key(child_title)
        for child_title in child_titles
        if len(normalize_key(child_title)) >= 3
    ]
    result: list[dict[str, Any]] = []
    for material in materials:
        full_text = normalize_key(material_text(material))
        if title_key and chapter_title_matches_file(material, title):
            result.append(material)
            continue
        child_match_count = sum(1 for child_key in child_keys if child_key in full_text)
        if len(child_keys) >= 2 and child_match_count >= 2:
            result.append(material)
    return result


def matching_appendices(
    item: dict[str, Any],
    appendices: list[dict[str, Any]],
    *,
    allow_title_match: bool = True,
) -> list[dict[str, Any]]:
    title = str(item.get("title") or "")
    number = str(item.get("number") or "")
    item_code = appendix_code(number) or appendix_code(title)
    item_is_appendix = "附表" in number or "附表" in title or "空表" in title
    title_key = normalize_key(title)
    matches: list[dict[str, Any]] = []
    for appendix in appendices:
        appendix_title = str(appendix.get("title") or "")
        appendix_id = str(appendix.get("id") or "")
        appendix_key = normalize_key(appendix_title)
        app_code = appendix_code(appendix_title) or appendix_code(appendix_id)
        if item_code and app_code and item_code == app_code:
            matches.append(appendix)
            continue
        if item_is_appendix or not allow_title_match:
            continue
        if title_key and len(title_key) >= 3 and (title_key in appendix_key or appendix_key in title_key):
            matches.append(appendix)
    return matches


def appendix_material_score(material: dict[str, Any], appendix: dict[str, Any]) -> float:
    title = str(appendix.get("title") or "")
    score = material_score(material, title)
    title_key = normalize_key(title)
    text = normalize_key(material_text(material))
    file_text = normalize_key(material_file_text(material))
    if title_key and title_key in file_text:
        score += 260
    elif title_key and title_key in text:
        score += 120
    for term in title_terms(title):
        if term in file_text:
            score += 85
        elif term in text:
            score += 45
    return score


def project_customer_name(manifest: dict[str, Any]) -> str:
    identity = manifest.get("projectIdentity") if isinstance(manifest.get("projectIdentity"), dict) else {}
    return clean_text(
        manifest.get("customerName")
        or identity.get("customerCanonicalName")
        or identity.get("customerName")
        or identity.get("owner")
        or ""
    )


def customer_rule_matches(project_customer: str, rule_customer: Any) -> bool:
    if not project_customer:
        return True
    project_key = normalize_key(project_customer)
    rule_key = normalize_key(rule_customer)
    return bool(project_key and rule_key and (project_key == rule_key or project_key in rule_key or rule_key in project_key))


def table_rule_score(table_title: Any, rule_title: Any) -> float:
    code_score = appendix_rule_code_score(table_title, rule_title)
    if code_score:
        return code_score
    left = normalize_key(table_title)
    right = normalize_key(rule_title)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return 0.88
    shared = len(set(left) & set(right))
    total = len(set(left) | set(right))
    return shared / total if total else 0.0


def find_source_matrix_rule(manifest: dict[str, Any], appendix: dict[str, Any]) -> dict[str, Any]:
    matrix = manifest.get("appendixSourceMatrix") if isinstance(manifest.get("appendixSourceMatrix"), dict) else {}
    rows = matrix.get("rows") if isinstance(matrix.get("rows"), list) else []
    customer_name = project_customer_name(manifest)
    title = appendix.get("title") or appendix.get("id") or ""
    best: tuple[float, dict[str, Any]] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not customer_rule_matches(customer_name, row.get("customer")):
            continue
        score = table_rule_score(title, row.get("tableTitle"))
        if score < 0.82:
            continue
        customer_bonus = 0.3 if customer_rule_matches(customer_name, row.get("customer")) else 0
        rank = score + customer_bonus
        if best is None or rank > best[0]:
            best = (rank, row)
    return dict(best[1]) if best else {}


def source_matrix_rule_terms(rule: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "project": source_terms(rule.get("projectSources")),
        "standard": source_terms(rule.get("standardSources")),
        "other": source_terms(rule.get("otherSources")),
    }


def matrix_material_score(material: dict[str, Any], rule: dict[str, Any]) -> tuple[float, list[str]]:
    terms = source_matrix_rule_terms(rule)
    if not any(terms.values()):
        return 0.0, []
    text = normalize_key(material_text(material))
    tier = normalize_key(material.get("materialTier") or material.get("materialScope") or "")
    score = 0.0
    reasons: list[str] = []
    for scope, scope_terms in (("project", terms["project"]), ("standard", terms["standard"])):
        scope_hit = False
        if scope == "project":
            scope_hit = "project" in tier or "项目" in tier
        elif scope == "standard":
            scope_hit = "standard" in tier or "标准" in tier or "通用" in tier
        for term in scope_terms:
            term_key = normalize_key(term)
            if not term_key:
                continue
            if term_key in text:
                score += 420 if scope_hit else 260
                reasons.append(f"{scope} 来源规定命中：{term}")
            elif any(part and part in text for part in source_terms(term) if len(normalize_key(part)) >= 2):
                score += 180 if scope_hit else 120
                reasons.append(f"{scope} 来源规定部分命中：{term}")
    if score and "project" in tier:
        score += 30
    elif score and ("standard" in tier or "标准" in tier or "通用" in tier):
        score += 20
    return score, reasons[:6]


def source_routing_payload(rule: dict[str, Any], materials: list[dict[str, Any]]) -> dict[str, Any]:
    if not rule:
        return {}
    terms = source_matrix_rule_terms(rule)
    matched = [
        {
            "id": str(material.get("id") or material.get("materialId") or ""),
            "name": str(material.get("name") or material.get("cleanedFileName") or ""),
            "folderPath": str(material.get("folderPath") or ""),
            "materialTier": str(material.get("materialTier") or ""),
            "matchReason": str(material.get("matchReason") or ""),
        }
        for material in materials[:8]
        if material.get("sourceRouting")
    ]
    manual_terms = [term for term in terms["other"] if any(token in term for token in ("人工", "收集", "项目定制收集"))]
    tender_terms = [term for term in terms["other"] if any(token in term for token in ("招标", "响应招标"))]
    status = "matched" if matched else ("manual_required" if manual_terms else ("tender_parse_fields" if tender_terms else "missing_source"))
    return {
        "status": status,
        "source": "appendix_source_matrix",
        "ruleId": str(rule.get("id") or ""),
        "customer": str(rule.get("customer") or ""),
        "tableTitle": str(rule.get("tableTitle") or ""),
        "projectSources": terms["project"],
        "standardSources": terms["standard"],
        "otherSources": terms["other"],
        "matchedMaterials": matched,
        "manualRequired": bool(manual_terms),
        "useTenderParseFields": bool(tender_terms),
    }


def item_source_rule_title(number: str, title: str) -> str:
    title_text = clean_text(title)
    number_text = clean_text(number)
    if number_text.startswith("附表") and number_text not in title_text:
        return " ".join(part for part in (number_text, title_text) if part)
    return title_text or number_text


def source_routing_for_item(
    manifest: dict[str, Any],
    *,
    number: str,
    title: str,
    materials: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rule_probe = {
        "id": item_source_rule_title(number, title) or title,
        "title": item_source_rule_title(number, title) or title,
    }
    source_rule = find_source_matrix_rule(manifest, rule_probe)
    if not source_rule:
        return {}, []
    routed_materials = recommended_materials_for_appendix(
        rule_probe,
        materials,
        source_rule=source_rule,
    )
    return source_routing_payload(source_rule, routed_materials), routed_materials[:5]


def recommended_materials_for_appendix(
    appendix: dict[str, Any],
    materials: list[dict[str, Any]],
    *,
    source_rule: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    has_source_rule = bool(source_rule and any(source_matrix_rule_terms(source_rule).values()))
    for material in dedupe_materials(materials):
        item = dict(material)
        rule_score, reasons = matrix_material_score(item, source_rule or {})
        if has_source_rule and not rule_score:
            continue
        if rule_score:
            item["matchReason"] = "；".join([*(reasons or []), str(item.get("matchReason") or "")]).strip("；")
            item["sourceRouting"] = {
                "source": "appendix_source_matrix",
                "ruleId": str((source_rule or {}).get("id") or ""),
                "reasons": reasons,
            }
        item["_sourceMatrixScore"] = rule_score
        ranked.append(item)
    return sorted(
        ranked,
        key=lambda material: (float(material.get("_sourceMatrixScore") or 0), appendix_material_score(material, appendix)),
        reverse=True,
    )


def build_appendix_task(
    appendix: dict[str, Any],
    recommended_materials: list[dict[str, Any]],
    parse_fields: list[dict[str, Any]] | None = None,
    source_routing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields = appendix.get("availableParseFields") or appendix.get("fields") or []
    if not isinstance(fields, list):
        fields = []
    merged_fields: list[dict[str, Any]] = []
    seen_fields: set[str] = set()
    for field in list(fields) + list(parse_fields or []):
        if not isinstance(field, dict):
            continue
        key = str(field.get("id") or field.get("label") or field.get("title") or field.get("key") or "").strip()
        if not key or key in seen_fields:
            continue
        seen_fields.add(key)
        merged_fields.append(field)
    return {
        "id": str(appendix.get("id") or appendix.get("title") or "APP-UNKNOWN"),
        "title": str(appendix.get("title") or "招标附表空表"),
        "sourceFile": str(appendix.get("sourceFile") or appendix.get("source_file") or ""),
        "docxPath": str(appendix.get("docxPath") or appendix.get("docx_path") or ""),
        "workspacePath": str(appendix.get("workspacePath") or appendix.get("workspace_path") or ""),
        "rowCount": appendix.get("rowCount") or appendix.get("row_count") or 0,
        "availableParseFields": merged_fields,
        "sourceRouting": dict(source_routing or {}),
        "recommendedMaterials": [
            {k: v for k, v in {**dict(material), "usage": "table_source"}.items() if k != "_sourceMatrixScore"}
            for material in recommended_materials[:5]
        ],
    }


def build_fill_task(item: dict[str, Any], appendix: dict[str, Any], gap_id: str) -> dict[str, Any]:
    appendix_id = str(appendix.get("id") or appendix.get("title") or "APP-UNKNOWN")
    title = str(item.get("title") or "待填写内容")
    return {
        "id": f"FILL-{gap_id}-{appendix_id}",
        "skill": "bid-tech-table-filler",
        "status": "pending",
        "title": f"填写{appendix.get('title') or title}",
        "blankSource": {
            "id": appendix_id,
            "title": str(appendix.get("title") or "招标附表空表"),
            "sourceFile": str(appendix.get("sourceFile") or appendix.get("source_file") or ""),
            "docxPath": str(appendix.get("docxPath") or appendix.get("docx_path") or ""),
            "workspacePath": str(appendix.get("workspacePath") or appendix.get("workspace_path") or ""),
        },
        "requiredReferences": ["素材库文件", "招标解析字段"],
    }


def build_material_fill_task(item: dict[str, Any], material: dict[str, Any], gap_id: str) -> dict[str, Any]:
    material_id = str(material.get("id") or material.get("materialId") or "MAT-UNKNOWN")
    title = str(item.get("title") or material.get("name") or "待填写 Word")
    placeholder_labels = [
        str(label)
        for label in (material.get("placeholderLabels") or [])
        if str(label or "").strip()
    ]
    return {
        "id": f"FILL-{gap_id}-{material_id}",
        "skill": "bid-tech-word-placeholder-filler",
        "status": "pending",
        "title": f"填写{title}",
        "blankSource": {
            "id": material_id,
            "title": str(material.get("name") or title),
            "sourceFile": str(material.get("name") or ""),
            "materialId": material_id,
            "folderPath": str(material.get("folderPath") or ""),
            "path": str(material.get("path") or ""),
            "cleanedFileName": str(material.get("cleanedFileName") or ""),
            "placeholderCount": int(material.get("placeholderCount") or 0),
            "placeholderLabels": placeholder_labels,
            "placeholderSamples": list(material.get("placeholderSamples") or []),
            "sourceType": "material_fill_template",
        },
        "requiredReferences": ["素材库文件", "招标解析字段", "项目投标机型"],
    }


def material_scope_payload(manifest: dict[str, Any], materials: list[dict[str, Any]]) -> dict[str, Any]:
    scope = manifest.get("materialScope") if isinstance(manifest.get("materialScope"), dict) else {}
    paths = scope.get("paths") or [
        str(item.get("path") or "")
        for item in scope.get("readableScopes") or []
        if isinstance(item, dict)
    ]
    matched_paths = sorted(
        {
            str(material.get("folderPath") or "")
            for material in materials
            if str(material.get("folderPath") or "")
        }
    )
    return {
        "allowedPaths": [str(path) for path in paths if str(path or "").strip()],
        "actualMatchedPaths": matched_paths,
    }


def turbine_check(materials: list[dict[str, Any]]) -> dict[str, str]:
    if not materials:
        return {"status": "unknown", "reason": "当前目录项未命中可用素材。"}
    return {"status": "generic", "reason": "素材未标记冲突机型，可作为当前投标机型候选。"}


def evidence_refs(materials: list[dict[str, Any]], appendices: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for material in materials[:6]:
        refs.append(
            {
                "type": "material",
                "id": str(material.get("id") or ""),
                "title": str(material.get("name") or material.get("id") or "素材"),
                "folderPath": str(material.get("folderPath") or ""),
            }
        )
    for appendix in appendices or []:
        refs.append(
            {
                "type": "appendix",
                "id": str(appendix.get("id") or ""),
                "title": str(appendix.get("title") or "招标附表空表"),
                "sourceFile": str(appendix.get("sourceFile") or appendix.get("source_file") or ""),
            }
        )
    return refs


def build_gap_plan(manifest: dict[str, Any]) -> dict[str, Any]:
    toc = load_json(Path(str(manifest["tocJsonPath"])))
    parse_result_path = Path(str(manifest.get("parseResultPath") or ""))
    parse_result = load_json(parse_result_path) if parse_result_path.exists() else {}
    items = toc_items(toc)
    appendices = appendices_from_parse(parse_result)
    parse_fields = parse_fields_from_parse(parse_result)
    raw_wiki_dir = str(manifest.get("wikiDir") or "").strip()
    wiki_index = wiki_cards_by_section(Path(raw_wiki_dir) if raw_wiki_dir else None)
    project_turbine_model = manifest.get("projectTurbineModel") if isinstance(manifest.get("projectTurbineModel"), dict) else {}
    indexed_materials = material_index_from_manifest(manifest)
    allowed_paths = material_scope_paths(manifest)
    toc_materials_all: list[dict[str, Any]] = []
    for toc_item in items:
        toc_materials_all.extend(normalize_material_refs(toc_item))
    parent_coverages: dict[str, dict[str, Any]] = {}
    plan_items: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        number = str(item.get("number") or "").strip()
        number_key = toc_number_key(number)
        title = str(item.get("title") or "").strip() or f"目录项-{index}"
        gap_id = f"GAP-{index:04d}"
        toc_materials = resolve_material_hints(normalize_material_refs(item), indexed_materials, allowed_paths)
        wiki_materials = resolve_material_hints(list(wiki_index.get(number) or []), indexed_materials, allowed_paths)
        index_materials = matching_materials_for_title(indexed_materials, title)
        candidate_materials = dedupe_materials(toc_materials + wiki_materials + index_materials)
        source_rule_pool = dedupe_materials(candidate_materials + indexed_materials + toc_materials_all)
        item_source_routing, item_source_materials = source_routing_for_item(
            manifest,
            number=number,
            title=title,
            materials=source_rule_pool,
        )
        matched_material: dict[str, Any] | None = None
        alternative_materials: list[dict[str, Any]] = []
        structural = is_structural(item, items)
        fill_tasks: list[dict[str, Any]] = []
        required_inputs: list[dict[str, Any]] = []
        appendix_matches = matching_appendices(item, appendices, allow_title_match=not structural)
        appendix_tasks: list[dict[str, Any]] = []
        decision = ""
        next_actions: list[str] = []
        coverage_role = ""
        covered_by_parent = ""
        usage = ""

        parent_key = number_key.split(".")[0] if "." in number_key else ""
        parent_coverage = parent_coverages.get(parent_key) if parent_key else None
        if parent_coverage:
            parent_decision = str(parent_coverage.get("decision") or "ready")
            status = "needs_input" if parent_decision == "fill_required" else "matched"
            decision = parent_decision
            usage = "covered_by_parent"
            coverage_role = "covered_by_parent"
            covered_by_parent = str(parent_coverage.get("id") or "")
            matched_materials = []
            gap_reason = f"已由父章节“{parent_coverage.get('title') or parent_key}”整章素材覆盖。"
            next_actions = ["ai_fill_word"] if parent_decision == "fill_required" else ["s4_merge_material"]
        elif appendix_matches:
            recommended_pool = dedupe_materials(candidate_materials + indexed_materials + toc_materials_all)
            appendix_tasks = []
            for appendix in appendix_matches:
                source_rule = find_source_matrix_rule(manifest, appendix)
                recommended = recommended_materials_for_appendix(
                    appendix,
                    recommended_pool,
                    source_rule=source_rule,
                )
                appendix_tasks.append(
                    build_appendix_task(
                        appendix,
                        recommended,
                        parse_fields,
                        source_routing=source_routing_payload(source_rule, recommended),
                    )
                )
            fill_tasks = [build_fill_task(item, appendix, gap_id) for appendix in appendix_matches]
            required_inputs.append({"type": "ai_fill", "label": "选择参考素材并填写空表"})
            status = "needs_input"
            decision = "fill_required"
            usage = "appendix_fill"
            matched_materials = []
            alternative_materials = dedupe_materials(
                [
                    material
                    for appendix in appendix_matches
                    for material in recommended_materials_for_appendix(
                        appendix,
                        recommended_pool,
                        source_rule=find_source_matrix_rule(manifest, appendix),
                    )[:5]
                ]
            )
            gap_reason = "解析阶段已生成空副表/Word，需要进入 S3 发起填写任务。"
            next_actions = ["ai_fill_appendix", "select_reference_material", "manual_upload"]
        elif structural:
            children = chapter_children(item, items)
            child_titles = [str(child.get("title") or "") for child in children]
            chapter_candidates = strong_chapter_master_candidates(
                dedupe_materials(candidate_materials + indexed_materials + toc_materials_all),
                title,
                child_titles,
            )
            matched_material, alternative_materials = pick_chapter_master_material(
                chapter_candidates,
                title,
                child_titles,
            )
            if matched_material:
                coverage_role = "chapter_master"
                matched_materials = [matched_material]
                parent_fill_required = material_requires_fill(matched_material)
                if parent_fill_required:
                    fill_tasks = [build_material_fill_task(item, matched_material, gap_id)]
                    required_inputs.append({"type": "ai_fill", "label": "填写整章 Word 后覆盖子目录"})
                    status = "needs_input"
                    decision = "fill_required"
                    usage = "chapter_fill"
                    gap_reason = "已匹配到整章待填写 Word，可填写后覆盖本章及其子节。"
                    next_actions = ["ai_fill_word", "select_reference_material", "manual_upload"]
                else:
                    status = "matched"
                    decision = "ready"
                    usage = "chapter_master"
                    gap_reason = "允许范围内已有整章 Word，可覆盖本章及其子节。"
                    next_actions = ["s4_merge_material"]
                parent_coverages[number_key] = {
                    "id": gap_id,
                    "title": title,
                    "material": matched_material,
                    "decision": decision,
                }
            else:
                status = "structural"
                decision = "ready"
                usage = "structural"
                matched_materials = []
                gap_reason = "结构性目录项，不直接要求素材。"
                next_actions = ["s4_merge_material"]
        elif candidate_materials:
            matched_material, alternative_materials = pick_material(candidate_materials, title)
            if material_requires_fill(matched_material):
                fill_tasks = [build_material_fill_task(item, matched_material, gap_id)] if matched_material else []
                required_inputs.append({"type": "ai_fill", "label": "选择参考素材并填写待填写 Word"})
                status = "needs_input"
                decision = "fill_required"
                usage = "section_fill"
                matched_materials = []
                alternative_materials = dedupe_materials(([matched_material] if matched_material else []) + alternative_materials)
                # 非附表正文缺口：给候选附段落级证据召回（A 层 evidenceSegments），
                # 让下游能定位素材内具体段落；无片段则退化为文件级（matchReason 不变）。
                alternative_materials = attach_recalled_segments(alternative_materials, title)
                gap_reason = "已匹配到待填写 Word 模板，需要先由 AI 填写后再进入 S4 合并。"
                next_actions = ["ai_fill_word", "select_reference_material", "manual_upload"]
            else:
                status = "matched"
                decision = "ready"
                usage = str((matched_material or {}).get("usage") or "section_merge")
                matched_materials = [matched_material] if matched_material else []
                # ready 态也召回片段，供 S4 合并/复核时定位证据；matched + 备选都附。
                matched_materials = attach_recalled_segments(matched_materials, title)
                alternative_materials = attach_recalled_segments(alternative_materials, title)
                gap_reason = "允许范围内已有可用素材。"
                next_actions = ["s4_merge_material"]
        else:
            status = "missing"
            decision = "material_required"
            usage = ""
            matched_materials = []
            gap_reason = "目录项未匹配到素材库 Wiki 或补料记录。"
            required_inputs.append({"type": "upload", "label": "上传客户资料或选择已有素材"})
            next_actions = ["manual_upload", "select_material", "ignore"]

        plan_items.append(
            {
                "id": gap_id,
                "tocItemId": str(item.get("id") or number or gap_id),
                "number": number,
                "title": title,
                "level": int(item.get("level") or 1),
                "annotation": str(item.get("annotation") or ""),
                "source": str(item.get("source") or ""),
                "reason": str(item.get("reason") or ""),
                "section": _section_label(number, title),
                "status": status,
                "decision": decision,
                "usage": usage,
                "coverageRole": coverage_role,
                "coveredByParent": covered_by_parent,
                "priority": "high" if status in {"needs_input", "missing"} else "medium",
                "matchedMaterials": matched_materials,
                "candidateMaterials": alternative_materials,
                "sourceRouting": item_source_routing,
                "sourceRoutedMaterials": [
                    {k: v for k, v in {**dict(material), "usage": "table_source"}.items() if k != "_sourceMatrixScore"}
                    for material in item_source_materials
                ],
                "appendixTasks": appendix_tasks,
                "requiredInputs": required_inputs,
                "fillTasks": fill_tasks,
                "resolvedArtifacts": [],
                "reviewNotes": [],
                "gapReason": gap_reason,
                "projectTurbineModel": project_turbine_model,
                "materialScope": material_scope_payload(manifest, matched_materials + alternative_materials),
                "turbineCheck": turbine_check(matched_materials + alternative_materials),
                "nextActions": next_actions,
                "evidenceRefs": evidence_refs(matched_materials + alternative_materials, appendix_matches),
            }
        )

    summary = summarize(plan_items)
    integrity = coverage_integrity(items, plan_items, summary)
    if integrity["coverageStatus"] != "passed":
        raise RuntimeError(
            "gap planner did not produce one result per confirmed TOC item: "
            f"expected {integrity['expectedTocItems']}, got {integrity['actualPlanItems']}"
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "projectId": str(manifest.get("projectId") or ""),
        "projectName": str(manifest.get("projectName") or ""),
        "bidType": str(manifest.get("bidType") or "技术标"),
        "customerName": project_customer_name(manifest),
        "appendixSourceMatrixPath": str(manifest.get("appendixSourceMatrixPath") or ""),
        "projectTurbineModel": project_turbine_model,
        "status": "ready",
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "summary": summary,
        "items": plan_items,
        "integrity": integrity,
    }


def summarize(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(item.get("status") or "") for item in items)
    decision_counts = Counter(str(item.get("decision") or "") for item in items)
    return {
        "totalTocItems": len(items),
        "matchedCount": counts.get("matched", 0),
        "missingCount": counts.get("missing", 0) + counts.get("needs_input", 0),
        "resolvedCount": counts.get("resolved", 0),
        "ignoredCount": counts.get("ignored", 0),
        "structuralCount": counts.get("structural", 0),
        "fillableTaskCount": sum(len(item.get("fillTasks") or []) for item in items),
        "blockingCount": counts.get("missing", 0) + counts.get("needs_input", 0) + counts.get("filling", 0),
        "readyCount": decision_counts.get("ready", 0),
        "fillRequiredCount": decision_counts.get("fill_required", 0),
        "materialRequiredCount": decision_counts.get("material_required", 0),
        "reviewRequiredCount": decision_counts.get("review_required", 0),
        "appendixTaskCount": sum(len(item.get("appendixTasks") or []) for item in items),
    }


def coverage_identity(item: dict[str, Any], index: int) -> str:
    number = str(item.get("number") or "").strip()
    title = str(item.get("title") or "").strip()
    return f"{index}:{number}:{title}"


def coverage_integrity(
    toc_entries: list[dict[str, Any]],
    plan_items: list[dict[str, Any]],
    summary: dict[str, int],
) -> dict[str, Any]:
    expected = [coverage_identity(item, index) for index, item in enumerate(toc_entries, start=1)]
    actual = [coverage_identity(item, index) for index, item in enumerate(plan_items, start=1)]
    expected_set = set(expected)
    actual_set = set(actual)
    duplicate_actual = sorted({item for item in actual if actual.count(item) > 1})
    missing = [item for item in expected if item not in actual_set]
    extra = [item for item in actual if item not in expected_set]
    coverage_status = "passed" if expected == actual and not duplicate_actual else "failed"
    return {
        "status": "passed" if summary["blockingCount"] == 0 else "blocked",
        "blockingCount": summary["blockingCount"],
        "coverageStatus": coverage_status,
        "expectedTocItems": len(expected),
        "actualPlanItems": len(actual),
        "missingTocItems": missing,
        "extraPlanItems": extra,
        "duplicatePlanItems": duplicate_actual,
        "checkedAt": now_iso(),
    }


def _section_label(number: str, title: str) -> str:
    if not number:
        return title
    if "." in number:
        return ".".join(number.split(".")[:-1]) or number
    return number


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--response", choices=("summary", "full"), default="summary")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    manifest = load_json(manifest_path)
    plan = build_gap_plan(manifest)
    output_file = Path(str(manifest.get("outputFile") or manifest_path.with_name("gap_plan.json")))
    output_file.parent.mkdir(parents=True, exist_ok=True)
    plan["planFile"] = str(output_file)
    plan["manifestPath"] = str(manifest_path)
    output_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.response == "full":
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "outputFile": str(output_file),
                    "summary": plan["summary"],
                    "tocItemCount": plan["integrity"]["expectedTocItems"],
                    "itemCount": len(plan["items"]),
                    "coverageStatus": plan["integrity"]["coverageStatus"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
