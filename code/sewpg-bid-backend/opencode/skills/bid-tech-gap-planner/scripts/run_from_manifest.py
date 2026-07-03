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
    """文件级匹配分，0~1 口径（对齐商务标 material_match_score 的归一化语义）。

    权重由旧版无界原始分整体 ÷200 等价缩放而来，排序行为与旧版严格一致；
    强命中可略超 1，展示侧（attach_recalled_segments / recall_material_segments）统一封顶 0.99。
    """
    text = normalize_key(material_text(material))
    title_key = normalize_key(title)
    score = float(material.get("confidence") or 0) * 0.05
    if title_key and title_key in text:
        score += 0.6
    for token in re.split(r"[与及和、/\\（）()]+", str(title or "")):
        token_key = normalize_key(token)
        if len(token_key) >= 2 and token_key in text:
            score += 0.08
    tier = str(material.get("materialTier") or "").lower()
    if tier == "project":
        score += 0.1
    elif tier == "customer":
        score += 0.06
    elif tier == "standard":
        score += 0.025
    if str(material.get("hasCleanedWord") or "").lower() == "true" or material.get("cleanedFileName"):
        score += 0.03
    return score


# ---------------------------------------------------------------------------
# 主题级弱关联召回（迁移自商务标 bid-business-gap-planner，技术标线内独立实现）
#
# 现有 material_match 的文件级匹配是「章节标题整串字面包含」，对「主题相关但文件名
# 对不上」的素材（如章节"试验、检验和监造" vs 素材"试验检测能力专题"/"质量保障体系"）
# 召不回。这里补一套同义词 + 中文分词相似度的弱关联召回，纯 stdlib、不调 LLM。
# ---------------------------------------------------------------------------

# 技术标领域同义词表：key 为章节主题的归一词，value 为可在素材文本里命中的近义/相关词。
# 基于真实投标技术卷里「漏召回」章节归纳，不照搬商务标的投标函/业绩那套。
TECH_TASK_SYNONYMS: dict[str, list[str]] = {
    "试验检验监造": ["试验", "检验", "监造", "试验检测", "型式试验", "检测能力", "质量保障", "质量保证", "全过程质量", "质量控制"],
    "安装调试试运行": ["安装", "调试", "试运行", "吊装", "安装要求", "调试解决方案"],
    "考核指标": ["考核", "可利用率", "功率曲线", "等效满负荷", "满负荷小时", "承诺值", "保证值", "承诺函"],
    "技术资料交付进度": ["技术资料", "交付", "交付进度", "图纸", "说明书", "保管", "包装"],
    "项目验收": ["验收", "质保", "出质保", "最终验收", "质量保证期"],
    "运行维护": ["运行维护", "运维", "售后", "技术服务"],
    # 以下为金标反评（正式技术卷逐节对照）归纳的漏召回主题组，均为风电投标领域
    # 通用词面，不绑定单一项目/客户。
    "风资源机位排布": ["风资源", "测风塔", "机位排布", "机位", "发电量", "不确定性", "风切变", "机组选型", "风资源评估"],
    "供货保障": ["供货保障", "生产能力", "生产基地", "制造基地", "供货制造", "设备制造", "生产制造", "产能", "物流", "运输保障"],
    "风机子系统": ["子系统", "叶片", "变桨", "齿轮箱", "主轴承", "发电机", "变流器", "主控", "偏航"],
    "场址设计安全性": ["场址设计安全性", "场址安全", "载荷", "极限载荷", "疲劳载荷", "载荷评估", "载荷安全", "安全等级", "净空", "塔筒安全", "变桨轴承"],
    "认证测试": ["认证", "型式认证", "设计认证", "样机", "测试", "试验检测", "电网性能"],
    "运输存储": ["运输", "物流", "运输路线", "存储", "堆场", "包装", "保管", "交货"],
    "技术参数指标": ["技术参数", "技术指标", "性能指标", "关键数据", "参数一览", "指标一览"],
    "投标业绩": ["业绩", "合同业绩", "供货业绩", "运行业绩", "投运"],
    "方案优势": ["方案优势", "整体优势", "技术路线", "先进性", "优势说明"],
}


def _tech_normalize_text(value: Any) -> str:
    """归一化：小写 + 去标点空白（与商务标 normalize_text 等价）。"""
    return re.sub(r"[\s　,，、.。:：;；()（）\[\]【】{}<>《》\"'`·_\-—/\\|]+", "", str(value or "").lower())


def _tech_tokenize_zh(value: str) -> list[str]:
    """中文 n-gram 切分（2~6 gram），用于无空格中文的 token Jaccard。"""
    text = _tech_normalize_text(value)
    tokens: list[str] = []
    seen: set[str] = set()
    for length in (6, 5, 4, 3, 2):
        for start in range(0, max(0, len(text) - length + 1)):
            tok = text[start : start + length]
            if tok not in seen:
                seen.add(tok)
                tokens.append(tok)
    return tokens


def _tech_similarity_score(a: str, b: str) -> float:
    """标题 a 与素材文本 b 的相似度（子串优先 + token Jaccard），迁移商务标算法。"""
    a = _tech_normalize_text(a)
    b = _tech_normalize_text(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b)) + 0.25
    a_tokens = set(_tech_tokenize_zh(a))
    b_tokens = set(_tech_tokenize_zh(b))
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / max(len(a_tokens | b_tokens), 1)


def _tech_synonym_terms_for_title(title: str) -> list[str]:
    """取章节标题命中的同义词组：标题里出现某主题 key 的任一词，则纳入该组全部近义词。"""
    title_key = _tech_normalize_text(title)
    terms: list[str] = []
    seen: set[str] = set()
    for topic, synonyms in TECH_TASK_SYNONYMS.items():
        group = [topic, *synonyms]
        # 标题命中该主题任一词，即认为属于该主题，纳入整组近义词供素材侧匹配。
        if any(_tech_normalize_text(word) and _tech_normalize_text(word) in title_key for word in group):
            for word in group:
                key = _tech_normalize_text(word)
                if len(key) >= 2 and key not in seen:
                    seen.add(key)
                    terms.append(word)
    return terms


def tech_synonym_hit_count(title: str, haystack: str) -> int:
    """章节标题的同义词组在素材文本里的加权命中数（长词×2，上限 8）。

    ≥4 字的领域词（如"场址设计安全性"）比 2 字泛词（如"载荷"）指向性强得多，
    加权后正确素材能与恰好蹭到两个泛词的噪声素材拉开排序差距。
    """
    normalized = _tech_normalize_text(haystack)
    if not normalized:
        return 0
    hits = 0
    for term in _tech_synonym_terms_for_title(title):
        key = _tech_normalize_text(term)
        if len(key) >= 2 and key in normalized:
            hits += 2 if len(key) >= 4 else 1
            if hits >= 8:
                return 8
    return hits


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
    # 权重与 material_score 同一 0~1 口径（旧版原始分 ÷200 等价缩放）。
    score = 0.0
    if title_key in seg_title:
        score += 0.3
    elif title_key in seg_text:
        score += 0.15
    for term in title_terms(title):
        if term in seg_title:
            score += 0.1
        elif term in seg_text:
            score += 0.04
    # 片段关键词双向命中：keyword 出现在标题里，或标题里的关键词出现在 keyword 里。
    keywords = segment.get("keywords") if isinstance(segment.get("keywords"), list) else []
    for keyword in keywords:
        key = normalize_key(keyword)
        if len(key) < 2:
            continue
        if key in title_key or title_key in key:
            score += 0.12
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
            # 展示分封顶 0.99（多关键词命中可略超 1），排序仍用未封顶的原始分。
            enriched["matchScore"] = round(min(score, 0.99), 2)
            scored.append((score, enriched))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [segment for _, segment in scored[:limit]]


def attach_recalled_segments(materials: list[dict[str, Any]], title: str, *, limit: int = 3) -> list[dict[str, Any]]:
    """给候选素材附上「与本目录标题相关的证据片段」+ 综合 matchScore（0~1，封顶 0.99）。

    用于非附表正文缺口：在文件级匹配之上叠加段落级证据，让下游 AI/人工能定位到
    素材内具体段落。matchScore = max(文件级分, 主题召回 topicRelevance) + 最佳片段
    加成（封顶 0.25），整体封顶 0.99，对齐商务标 0~1 打分口径。
    取 topicRelevance 兜底是因为主题召回的素材文件名往往与标题字面对不上，
    纯文件级分会把真实相关度显示得过低。不改动来源矩阵/附表路径。
    """
    enriched_list: list[dict[str, Any]] = []
    for material in materials:
        if not isinstance(material, dict):
            continue
        recalled = recall_material_segments(material, title, limit=limit)
        item = dict(material)
        base = max(material_score(material, title), _weak_recall_rank(material))
        segment_bonus = min(recalled[0]["matchScore"] if recalled else 0.0, 0.25)
        item["matchScore"] = round(min(base + segment_bonus, 0.99), 2)
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
    # 仅内部排序用，不外泄前端；加成随 material_score 归一化同比例（÷200）缩放，保持排序等价。
    score = material_score(material, title)
    text = normalize_key(material_text(material))
    file_text = normalize_key(material_file_text(material))
    title_key = normalize_key(title)
    if title_key and title_key in file_text:
        score += 2.6
    elif chapter_title_matches_file(material, title):
        score += 2.15
    elif title_key and title_key in text:
        score += 0.9
    for term in title_terms(title):
        if term in file_text:
            score += 0.29
        elif term in text:
            score += 0.11
    child_matches = 0
    for child_title in child_titles or []:
        child_key = normalize_key(child_title)
        if child_key and len(child_key) >= 3 and child_key in text:
            child_matches += 1
    score += child_matches * 0.35
    if str(material.get("materialTier") or "").lower() == "project":
        score += 0.15
    if str(material.get("materialTier") or "").lower() == "standard":
        score += 0.06
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


def sibling_folder_materials(
    matched: dict[str, Any] | None,
    materials: list[dict[str, Any]],
    title: str,
    *,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """同目录兄弟素材（金标反评 D3）：固定素材命中专题目录时，把同目录其余素材
    作为候选露出，供人工加选拼装（一章=多素材场景，如环境适应性/数字化智慧风场）。"""
    folder = str((matched or {}).get("folderPath") or "").rstrip("/")
    if not folder:
        return []
    matched_id = str((matched or {}).get("id") or "")
    siblings = []
    for material in materials:
        if not isinstance(material, dict):
            continue
        if str(material.get("folderPath") or "").rstrip("/") != folder:
            continue
        if str(material.get("id") or "") == matched_id or material_requires_fill(material):
            continue
        sib = dict(material)
        # 附名称相似度：项目根目录这类「非主题目录」下兄弟众多且 material_score
        # 常平分，靠素材名与章节标题的相似度把真相关的（如 承诺函 系列）排上来。
        name_sim = _tech_similarity_score(title, _material_name_stem(str(sib.get("name") or "")))
        if name_sim >= 0.2:
            sib["nameSimilarity"] = round(name_sim, 3)
        siblings.append(sib)
    siblings.sort(key=lambda m: material_score(m, title) + float(m.get("nameSimilarity") or 0), reverse=True)
    return [dict(m) for m in siblings[:limit]]


def matching_materials_for_title(materials: list[dict[str, Any]], title: str) -> list[dict[str, Any]]:
    title_key = normalize_key(title)
    if not title_key:
        return []
    return [
        material
        for material in materials
        if title_key in normalize_key(material_text(material))
    ]


def title_matches_file_name(material: dict[str, Any], title: str) -> bool:
    """章节标题是否命中素材的文件级名称（文件名/清洗稿名，不含目录路径）。

    只有文件名命中才允许固定素材自动定案（一份 doc = 一整章）；
    目录名撞章节名不算（那是「目录 = 章、目录下多份子素材」的拼装结构）。
    """
    title_key = normalize_key(title)
    return bool(title_key) and title_key in normalize_key(material_file_text(material))


def folder_prefix_for_title(material: dict[str, Any], title: str) -> str:
    """素材路径中与章节标题同名的目录前缀（无则空串）。

    如章节"数字化智慧风场专题" vs 路径"技术标/客户素材/华能集团/数字化智慧风场专题/
    智能风机部件监控系统"，返回到「数字化智慧风场专题」为止的前缀。
    目录名需 ≥4 个归一化字符（防「专题」这类短词误判）。
    """
    title_key = normalize_key(title)
    if not title_key:
        return ""
    parts = [p for p in str(material.get("folderPath") or "").split("/") if p]
    acc: list[str] = []
    for part in parts:
        acc.append(part)
        part_key = normalize_key(part)
        if len(part_key) >= 4 and (part_key in title_key or title_key in part_key):
            return "/".join(acc)
    return ""


def folder_member_materials(
    materials: list[dict[str, Any]],
    folder_prefix: str,
    title: str,
) -> list[dict[str, Any]]:
    """同名目录（含子目录）下的全部现成素材，按匹配分排序。

    按**目录名**跨分支收成员（金标反评：智慧风场专题在 通用素材/<机型> 与
    客户定制/<客户> 各有一个同名目录，答案两个分支都用了——只收命中素材所在
    分支会漏掉另一半骨架章节）。这些素材是确定相关的（目录即章节），全部进候选
    供人工拼装，带 literalFolderHit 标记以豁免 top-4 截断；待填写模板剔除。
    """
    dir_key = normalize_key(folder_prefix.rstrip("/").rsplit("/", 1)[-1])
    if not dir_key:
        return []
    members = []
    for material in materials:
        if not isinstance(material, dict) or material_requires_fill(material):
            continue
        segments_path = [p for p in str(material.get("folderPath") or "").split("/") if p]
        if not any(normalize_key(part) == dir_key for part in segments_path):
            continue
        member = dict(material)
        member["literalFolderHit"] = True
        member["matchReason"] = "章节同名目录素材（人工选用拼装）"
        members.append(member)
    members.sort(key=lambda m: material_score(m, title), reverse=True)
    return members


def route_folder_literal(
    candidate_materials: list[dict[str, Any]],
    indexed_materials: list[dict[str, Any]],
    title: str,
) -> dict[str, Any] | None:
    """字面命中仅来自「目录名撞章节名」时的路由：不自动定案，转素材匹配。

    返回 None 表示不适用（有文件名命中，或命中来自其他文本特征）。
    """
    if any(title_matches_file_name(m, title) for m in candidate_materials):
        return None
    folder_prefix = ""
    for material in candidate_materials:
        folder_prefix = folder_prefix_for_title(material, title)
        if folder_prefix:
            break
    if not folder_prefix:
        return None
    members = folder_member_materials(indexed_materials, folder_prefix, title)
    if not members:
        return None
    candidates = attach_recalled_segments(members, title)
    for candidate in candidates:
        candidate["literalFolderHit"] = True
    return {
        "status": "needs_input",
        "decision": "fill_required",
        "usage": "section_fill",
        "matched": [],
        "alternatives": candidates,
        "fill_tasks": [],
        "required_inputs": [{"type": "material_match", "label": "从章节同名目录素材中选用拼装"}],
        "gap_reason": f"章节与素材目录「{folder_prefix.rsplit('/', 1)[-1]}」同名，目录下 {len(candidates)} 份素材需人工选用拼装，不自动定案。",
        "next_actions": ["select_reference_material", "manual_upload"],
    }


def _material_topic_text(material: dict[str, Any]) -> str:
    """素材的主题文本池：文件名 + 路径 + 片段 topicKeywords/keywords/title/summary。

    用于主题级弱关联召回——把「主题相关但文件名对不上」的素材也纳入打分。
    """
    parts = [material_text(material)]
    for segment in material.get("evidenceSegments") or []:
        if not isinstance(segment, dict):
            continue
        parts.append(str(segment.get("title") or ""))
        parts.append(str(segment.get("summary") or ""))
        for key in ("topicKeywords", "keywords"):
            value = segment.get(key)
            if isinstance(value, list):
                parts.append(" ".join(str(v) for v in value))
    return " ".join(parts)


def topic_match_score(material: dict[str, Any], title: str) -> float:
    """章节标题与素材主题文本的弱关联相关度（0~1），迁移商务标 wiki_card_relevance 思路。

    取「分词相似度」与「同义词命中折算」的较大者：
    - similarity：标题 vs 素材主题池的子串/token Jaccard。
    - 同义词：命中 >=2 个折 0.45，命中 1 个折 0.3（标题主题被素材覆盖的信号）。
    返回 0 表示无主题关联。
    """
    pool = _material_topic_text(material)
    if not pool or not normalize_key(title):
        return 0.0
    sim = _tech_similarity_score(title, pool)
    syn_hits = tech_synonym_hit_count(title, pool)
    syn_score = 0.0
    if syn_hits >= 2:
        # 命中数越多排序越靠前（0.45 起步、封顶 0.75），避免同组素材打平分后排序随机。
        syn_score = min(0.45 + 0.05 * (syn_hits - 2), 0.75)
    elif syn_hits == 1:
        syn_score = 0.3
    return max(sim, syn_score)


def topic_match_materials(
    materials: list[dict[str, Any]],
    title: str,
    *,
    threshold: float = 0.2,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """主题级弱关联召回：从允许范围素材里挑与章节标题主题相关的素材。

    对每份素材算 topic_match_score，>= threshold 的纳入候选（附 topicRelevance），
    按分降序取前 limit。用于补「文件名对不上但主题相关」的素材，救字面召回的漏网。
    """
    title_key = normalize_key(title)
    if not title_key:
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for material in materials:
        if not isinstance(material, dict):
            continue
        score = topic_match_score(material, title)
        # 项目素材阈值放宽 ×0.6（金标反评 B 类：项目定制素材漏召回代价远大于噪声）
        if score >= (threshold * 0.6 if str(material.get("materialTier") or "").lower() == "project" else threshold):
            enriched = dict(material)
            enriched["topicRelevance"] = round(score, 3)
            enriched["matchReason"] = enriched.get("matchReason") or "主题相关素材（弱关联召回）"
            scored.append((score, enriched))
    # 路内排序也加层级加成：平分时项目/客户素材优先，避免 tie-break 按插入序把它们挤出路内上限。
    scored.sort(key=lambda pair: pair[0] + _tier_recall_bonus(pair[1]), reverse=True)
    return [material for _, material in scored[:limit]]


def _material_name_stem(name: str) -> str:
    """素材名词干：去扩展名、去「待填写-/定制-」等加工前缀、去尾部页码数字。"""
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", str(name or "")).strip()
    stem = re.sub(r"^(?:待填写|待补充|定制|模板)\s*[-—_]\s*", "", stem)
    return stem.strip()


def approx_name_match_materials(
    materials: list[dict[str, Any]],
    title: str,
    *,
    threshold: float = 0.34,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """近似名称召回（金标反评 D1）：章节标题 vs 素材名/清洗稿名 的相似度召回。

    补「整串包含」召不回的近名素材（如章节"投标机型项目场址设计安全性专题" vs
    素材"钢塔筒招标项目场址设计安全性.docx"）。只产候选，不自动定案。
    词干需 ≥4 个归一化字符（"专题"这类短目录词会把相似度打满，是噪声源）。
    """
    title_clean = str(title or "")
    if not normalize_key(title_clean):
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for material in materials:
        if not isinstance(material, dict):
            continue
        best = 0.0
        for name in (str(material.get("name") or ""), str(material.get("cleanedFileName") or "")):
            stem = _material_name_stem(name)
            if len(normalize_key(stem)) >= 4:
                best = max(best, _tech_similarity_score(title_clean, stem))
        # 项目素材阈值放宽 ×0.6（金标反评 B 类）
        if best >= (threshold * 0.6 if str(material.get("materialTier") or "").lower() == "project" else threshold):
            enriched = dict(material)
            enriched["nameSimilarity"] = round(best, 3)
            enriched["matchReason"] = enriched.get("matchReason") or "近似名称召回"
            scored.append((best, enriched))
    # 路内排序也加层级加成：平分时项目/客户素材优先，避免 tie-break 按插入序把它们挤出路内上限。
    scored.sort(key=lambda pair: pair[0] + _tier_recall_bonus(pair[1]), reverse=True)
    return [material for _, material in scored[:limit]]


def _segment_title_clean(segment: dict[str, Any]) -> str:
    """片段标题清洗：去头部编号（1.1 / 一、）与尾部页码数字，留纯标题词面。"""
    text = str(segment.get("title") or "").strip()
    text = re.sub(r"^\s*(?:[0-9]+(?:\.[0-9]+)*|[一二三四五六七八九十]+)\s*[、.．\s]\s*", "", text)
    return re.sub(r"[0-9]+\s*$", "", text).strip()


def segment_recall_materials(
    materials: list[dict[str, Any]],
    title: str,
    *,
    threshold: float = 0.45,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """片段级召回（金标反评 D2）：章节标题与素材片段标题相似即召回该素材。

    解决大报告章节复用——素材文件名对不上、但内部某片段正是本章内容
    （如"风资源评估报告"内的"项目概况"章 vs 目录项"项目概况"）。
    只用片段标题（真实文档章节头，信号干净）；不用 keywords——A 层关键词混有
    项目号/目录碎屑（MATPRJ、"专题"等），双向包含会产生大量假命中。
    """
    if not normalize_key(title):
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for material in materials:
        if not isinstance(material, dict):
            continue
        segments = [s for s in material.get("evidenceSegments") or [] if isinstance(s, dict)]
        if not segments:
            # 金标反评 A 类：PDF/xlsx 等未切片素材以文件名词干做伪片段，
            # 让片段路由对它们不失效（如 载荷安全性评估报告.pdf）。
            stem = _material_name_stem(str(material.get("name") or ""))
            if stem:
                segments = [{"title": stem}]
        best, best_seg = 0.0, ""
        for segment in segments:
            seg_title = _segment_title_clean(segment)
            if len(normalize_key(seg_title)) < 4:
                continue
            score = _tech_similarity_score(title, seg_title)
            if score > best:
                best, best_seg = score, seg_title
        # 项目素材阈值放宽 ×0.6（金标反评 B 类）
        if best >= (threshold * 0.6 if str(material.get("materialTier") or "").lower() == "project" else threshold):
            enriched = dict(material)
            enriched["segmentRecallScore"] = round(min(best, 0.99), 3)
            enriched["matchReason"] = enriched.get("matchReason") or f"片段级召回：{best_seg or '相关片段'}"
            scored.append((best, enriched))
    # 路内排序也加层级加成：平分时项目/客户素材优先，避免 tie-break 按插入序把它们挤出路内上限。
    scored.sort(key=lambda pair: pair[0] + _tier_recall_bonus(pair[1]), reverse=True)
    return [material for _, material in scored[:limit]]


def _tier_recall_bonus(material: dict[str, Any]) -> float:
    """召回排序的层级加成（金标反评 B 类）：项目素材是为本项目定制/收集的，
    正式标书大量复用（锡盟基地/物流方案/电量承诺书跨多章出现），排序上
    应压过靠同义词蹭分的通用素材。"""
    tier = str(material.get("materialTier") or "").lower()
    if tier == "project":
        return 0.12
    if tier == "customer":
        return 0.06
    return 0.0


def _weak_recall_rank(material: dict[str, Any]) -> float:
    # 三路求和：多路同时命中（名称+片段+主题一致指向）的素材优先于单路命中的；
    # 项目/客户素材另有层级加成。
    return (
        float(material.get("topicRelevance") or 0)
        + float(material.get("nameSimilarity") or 0)
        + float(material.get("segmentRecallScore") or 0)
        + _tier_recall_bonus(material)
    )


def weak_recall_materials(
    materials: list[dict[str, Any]],
    title: str,
    *,
    limit: int = 14,
) -> list[dict[str, Any]]:
    """弱关联召回统一入口：主题 + 近名 + 片段三路合并去重，按各路最高分排序取前 limit。

    金标反评方针：召回优先、允许牺牲准确率；所有产出只进候选（人工终审），不自动定案。
    """
    merged: dict[str, dict[str, Any]] = {}
    for pool in (
        topic_match_materials(materials, title),
        approx_name_match_materials(materials, title),
        segment_recall_materials(materials, title),
    ):
        for material in pool:
            key = str(material.get("id") or material.get("path") or material.get("name") or "")
            if not key:
                continue
            if key in merged:
                for field in ("topicRelevance", "nameSimilarity", "segmentRecallScore"):
                    if material.get(field) is not None and merged[key].get(field) is None:
                        merged[key][field] = material[field]
            else:
                merged[key] = dict(material)
    ranked = sorted(merged.values(), key=_weak_recall_rank, reverse=True)
    return ranked[:limit]


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
    # 仅内部排序用，不外泄前端；加成随 material_score 归一化同比例（÷200）缩放，保持排序等价。
    title = str(appendix.get("title") or "")
    score = material_score(material, title)
    title_key = normalize_key(title)
    text = normalize_key(material_text(material))
    file_text = normalize_key(material_file_text(material))
    if title_key and title_key in file_text:
        score += 1.3
    elif title_key and title_key in text:
        score += 0.6
    for term in title_terms(title):
        if term in file_text:
            score += 0.425
        elif term in text:
            score += 0.225
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


def _fill_template_trusted(template: dict[str, Any], pool: list[dict[str, Any]], title: str) -> bool:
    """弱召回主推的待填写模板是否可信到直接挂 AI 填写任务。

    金标反评发现的错误路由（5.8 各子系统专题被挂上"优势说明"模板）：模板靠
    同义词组蹭分登顶，但与章节主题无关——AI 拿错模板填出错误方向比漏召回更糟。
    可信条件（满足其一）：
    - 模板名称词干与章节标题字面相关（文件名命中或相似度 ≥0.3；比较前剥掉
      「（双TRB+碳纤叶片）」这类括号修饰——模板按目标章节命名，括号是配置后缀）；
    - 模板召回分明显领先现成素材（≥0.15），说明不是同义词蹭分的并列噪声。
    否则降级为素材匹配候选，交人工判断。
    """
    if title_matches_file_name(template, title):
        return True
    stem = _material_name_stem(str(template.get("name") or ""))
    stem_core = re.sub(r"[（(][^（）()]*[)）]", "", stem).strip()
    if max(
        _tech_similarity_score(title, stem),
        _tech_similarity_score(title, stem_core) if stem_core else 0.0,
    ) >= 0.3:
        return True
    ready_ranks = [_weak_recall_rank(m) for m in pool if not material_requires_fill(m)]
    if not ready_ranks:
        return False  # 名称不相关且无现成素材对照 → 不可信，宁判人工补料
    return _weak_recall_rank(template) - max(ready_ranks) >= 0.15


def route_weak_recall(
    item: dict[str, Any],
    indexed_materials: list[dict[str, Any]],
    title: str,
    gap_id: str,
) -> dict[str, Any] | None:
    """字面候选为空时的弱召回路由（金标反评 D1+D2+D4）。

    主题+近名+片段三路统一召回；命中「待填写模板」走 AI 填写，命中现成素材给
    top-4 候选人工勾选（候选≠决策）；三路全空返回 None（调用方判人工补料）。
    """
    pool = weak_recall_materials(indexed_materials, title)
    if not pool:
        return None
    primary = pool[0]
    if material_requires_fill(primary) and _fill_template_trusted(primary, pool, title):
        candidates = attach_recalled_segments(pool, title)
        candidates.sort(key=lambda m: float(m.get("matchScore") or 0), reverse=True)
        return {
            "status": "needs_input",
            "decision": "fill_required",
            "usage": "section_fill",
            "matched": [],
            "alternatives": candidates[:4],
            "fill_tasks": [build_material_fill_task(item, primary, gap_id)],
            "required_inputs": [{"type": "ai_fill", "label": "选择参考素材并填写待填写 Word"}],
            "gap_reason": "召回命中待填写模板，需先由 AI 填写后再进入 S4 合并。",
            "next_actions": ["ai_fill_word", "select_reference_material", "manual_upload"],
        }
    # material_match 候选是「选择即合并」列表，剔除待填写模板（它们只应走 AI 填写）。
    ready_pool = [m for m in pool if not material_requires_fill(m)]
    if not ready_pool:
        return None  # 池里只有不可信模板 → 宁判人工补料，不给错误方向
    candidates = attach_recalled_segments(ready_pool, title)
    candidates.sort(key=lambda m: float(m.get("matchScore") or 0), reverse=True)
    # 金标反评 B 类：召回到的项目素材不占 top-4 名额（正式标书大量复用项目定制
    # 素材，被通用素材挤出的代价最大），追加在后、另设上限防洪。
    project_extras = [
        m for m in candidates[4:]
        if str(m.get("materialTier") or "").lower() == "project"
    ][:4]
    return {
        "status": "needs_input",
        "decision": "fill_required",
        "usage": "section_fill",
        "matched": [],
        "alternatives": candidates[:4] + project_extras,
        "fill_tasks": [],
        "required_inputs": [{"type": "material_match", "label": "从召回候选中选用素材"}],
        "gap_reason": "弱关联召回命中（主题/近名/片段），可选用素材后合入或补充。",
        "next_actions": ["select_reference_material", "manual_upload"],
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
                    alternative_materials = alternative_materials[:4]
                    gap_reason = "已匹配到整章待填写 Word，可填写后覆盖本章及其子节。"
                    next_actions = ["ai_fill_word", "select_reference_material", "manual_upload"]
                else:
                    status = "matched"
                    decision = "ready"
                    usage = "chapter_master"
                    # 金标反评 D3：整章素材的备选并入同目录兄弟素材（如承诺函章的
                    # 电量承诺书），人工可加选拼装；top-4 截断。
                    alternative_materials = dedupe_materials(
                        alternative_materials + sibling_folder_materials(matched_material, indexed_materials, title)
                    )[:4]
                    gap_reason = "允许范围内已有整章 Word，可覆盖本章及其子节。"
                    next_actions = ["s4_merge_material"]
                parent_coverages[number_key] = {
                    "id": gap_id,
                    "title": title,
                    "material": matched_material,
                    "decision": decision,
                }
            else:
                # 无子节的结构项（如附表1/2/3 成果表）正式标书里往往有实质内容：
                # 也跑弱召回（金标反评 D5），命中给候选人工确认；全空才保持结构项。
                routed = route_weak_recall(item, indexed_materials, title, gap_id) if not children else None
                if routed:
                    status = routed["status"]
                    decision = routed["decision"]
                    usage = routed["usage"]
                    matched_materials = routed["matched"]
                    alternative_materials = routed["alternatives"]
                    fill_tasks = routed["fill_tasks"]
                    required_inputs.extend(routed["required_inputs"])
                    gap_reason = routed["gap_reason"]
                    next_actions = routed["next_actions"]
                else:
                    status = "structural"
                    decision = "ready"
                    usage = "structural"
                    matched_materials = []
                    gap_reason = "结构性目录项，不直接要求素材。"
                    next_actions = ["s4_merge_material"]
        elif candidate_materials and (folder_routed := route_folder_literal(candidate_materials, indexed_materials, title)):
            # 字面命中仅来自「目录名撞章节名」（如 数字化智慧风场专题/ 目录）：
            # 目录=章、目录下多份子素材，随便挑一份自动定案是错的——转素材匹配，
            # 目录成员全部进候选（豁免 top-4）供人工拼装。
            status = folder_routed["status"]
            decision = folder_routed["decision"]
            usage = folder_routed["usage"]
            matched_materials = folder_routed["matched"]
            alternative_materials = folder_routed["alternatives"]
            fill_tasks = folder_routed["fill_tasks"]
            required_inputs.extend(folder_routed["required_inputs"])
            gap_reason = folder_routed["gap_reason"]
            next_actions = folder_routed["next_actions"]
        elif candidate_materials:
            # 固定素材自动定案只信文件名命中；有文件名命中时优先从中选主素材。
            file_hits = [m for m in candidate_materials if title_matches_file_name(m, title)]
            pick_pool = file_hits or candidate_materials
            matched_material, alternative_materials = pick_material(pick_pool, title)
            if file_hits and len(file_hits) < len(candidate_materials):
                others = [m for m in candidate_materials if m not in file_hits]
                alternative_materials = dedupe_materials(alternative_materials + others)
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
                alternative_materials.sort(key=lambda m: float(m.get("matchScore") or 0), reverse=True)
                alternative_materials = alternative_materials[:4]
                gap_reason = "已匹配到待填写 Word 模板，需要先由 AI 填写后再进入 S4 合并。"
                next_actions = ["ai_fill_word", "select_reference_material", "manual_upload"]
            else:
                status = "matched"
                decision = "ready"
                usage = str((matched_material or {}).get("usage") or "section_merge")
                matched_materials = [matched_material] if matched_material else []
                # ready 态也召回片段，供 S4 合并/复核时定位证据；matched + 备选都附。
                matched_materials = attach_recalled_segments(matched_materials, title)
                # 金标反评 D3：备选并入同目录兄弟素材（一章=多素材拼装场景，人工可加选），
                # 统一按匹配分排序取 top-4。
                alternative_materials = dedupe_materials(
                    alternative_materials + sibling_folder_materials(matched_material, indexed_materials, title)
                )
                alternative_materials = attach_recalled_segments(alternative_materials, title)
                alternative_materials.sort(key=lambda m: float(m.get("matchScore") or 0), reverse=True)
                alternative_materials = alternative_materials[:4]
                gap_reason = "允许范围内已有可用素材。"
                next_actions = ["s4_merge_material"]
        else:
            # 字面候选为空：弱关联召回统一兜底（主题+近名+片段，金标反评 D1/D2）。
            # 命中只进候选（人工终审），不自动定案；三路全空才判人工补料（D4）。
            routed = route_weak_recall(item, indexed_materials, title, gap_id)
            if routed:
                status = routed["status"]
                decision = routed["decision"]
                usage = routed["usage"]
                matched_materials = routed["matched"]
                alternative_materials = routed["alternatives"]
                fill_tasks = routed["fill_tasks"]
                required_inputs.extend(routed["required_inputs"])
                gap_reason = routed["gap_reason"]
                next_actions = routed["next_actions"]
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
