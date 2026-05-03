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


def normalize_key(value: Any) -> str:
    return re.sub(r"[\s　,，、.。:：;；()（）\[\]【】{}<>《》\"'`·_\-—/\\|]+", "", str(value or "").lower())


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
    text = str(value or "").strip()
    match = re.search(r"附表\s*([A-Za-z]?\s*\.?\s*\d+(?:\.\d+)*)", text)
    if not match:
        return ""
    return re.sub(r"\s+", "", match.group(1)).upper().lstrip(".")


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
        output.append(
            {
                "id": str(raw.get("id") or raw.get("materialId") or ""),
                "name": name,
                "path": str(raw.get("path") or (f"{folder_path}/{name}" if folder_path and name else "")),
                "folderPath": folder_path,
                "materialTier": str(raw.get("materialTier") or ""),
                "cleanedFileName": str(raw.get("cleanedFileName") or ""),
                "hasCleanedWord": bool(raw.get("hasCleanedWord") or raw.get("cleanedFileName")),
                "usage": "section_merge",
                "matchReason": "允许素材范围内的素材索引候选",
                "confidence": 0.74,
                "source": "material_index",
                "turbineModelLabel": str(raw.get("turbineModelLabel") or ""),
            }
        )
    return output


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
        for key in ("name", "path", "folderPath", "cleanedFileName", "matchReason")
    )


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


def wind_master_score(material: dict[str, Any]) -> float:
    text = normalize_key(material_text(material))
    score = material_score(material, "风资源评估与机位排布方案")
    if "风资源评估与机位排布方案" in material_text(material):
        score += 500
    if "技术标风资源评估与机位排布方案" in text:
        score += 220
    if "定制风资源评估与机位排布方案" in text:
        score += 180
    if "风资源评估报告" in text:
        score -= 180
    if "发电量担保" in text:
        score -= 260
    if "承诺保证值" in text or "承诺考核值" in text:
        score -= 180
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


def pick_wind_master_material(candidates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    materials = dedupe_materials(candidates)
    if not materials:
        return None, []
    ranked = sorted(materials, key=wind_master_score, reverse=True)
    selected = dict(ranked[0])
    selected["usage"] = "chapter_master"
    selected["matchReason"] = "整章素材覆盖第3章“风资源评估与机位排布方案”。"
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


def wind_material_candidates(materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        material
        for material in materials
        if "风资源" in material_text(material) or "机位排布" in material_text(material) or "机组选型排布" in material_text(material)
    ]


def matching_appendices(item: dict[str, Any], appendices: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        if item_is_appendix:
            continue
        if title_key and len(title_key) >= 3 and (title_key in appendix_key or appendix_key in title_key):
            matches.append(appendix)
    return matches


def appendix_material_score(material: dict[str, Any], appendix: dict[str, Any]) -> float:
    title = str(appendix.get("title") or "")
    score = material_score(material, title)
    title_key = normalize_key(title)
    text = normalize_key(material_text(material))
    if "风资源评估与机位排布方案" in title_key:
        score += wind_master_score(material)
    if "发电量" in title_key:
        if "发电量" in text:
            score += 120
        if "担保" in text:
            score += 40
    if "机位" in title_key and "机位" in text:
        score += 80
    return score


def recommended_materials_for_appendix(
    appendix: dict[str, Any],
    materials: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        dedupe_materials(materials),
        key=lambda material: appendix_material_score(material, appendix),
        reverse=True,
    )


def build_appendix_task(appendix: dict[str, Any], recommended_materials: list[dict[str, Any]]) -> dict[str, Any]:
    fields = appendix.get("availableParseFields") or appendix.get("fields") or []
    if not isinstance(fields, list):
        fields = []
    return {
        "id": str(appendix.get("id") or appendix.get("title") or "APP-UNKNOWN"),
        "title": str(appendix.get("title") or "招标附表空表"),
        "sourceFile": str(appendix.get("sourceFile") or appendix.get("source_file") or ""),
        "docxPath": str(appendix.get("docxPath") or appendix.get("docx_path") or ""),
        "workspacePath": str(appendix.get("workspacePath") or appendix.get("workspace_path") or ""),
        "rowCount": appendix.get("rowCount") or appendix.get("row_count") or 0,
        "availableParseFields": fields,
        "recommendedMaterials": [
            {**dict(material), "usage": "table_source"}
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


def is_wind_master_item(item: dict[str, Any]) -> bool:
    return toc_number_key(item.get("number")) == "3" and "风资源评估" in str(item.get("title") or "") and "机位排布" in str(item.get("title") or "")


def build_gap_plan(manifest: dict[str, Any]) -> dict[str, Any]:
    toc = load_json(Path(str(manifest["tocJsonPath"])))
    parse_result_path = Path(str(manifest.get("parseResultPath") or ""))
    parse_result = load_json(parse_result_path) if parse_result_path.exists() else {}
    items = toc_items(toc)
    appendices = appendices_from_parse(parse_result)
    raw_wiki_dir = str(manifest.get("wikiDir") or "").strip()
    wiki_index = wiki_cards_by_section(Path(raw_wiki_dir) if raw_wiki_dir else None)
    project_turbine_model = manifest.get("projectTurbineModel") if isinstance(manifest.get("projectTurbineModel"), dict) else {}
    indexed_materials = material_index_from_manifest(manifest)
    toc_materials_all: list[dict[str, Any]] = []
    for toc_item in items:
        toc_materials_all.extend(normalize_material_refs(toc_item))
    all_wind_materials = wind_material_candidates(dedupe_materials(indexed_materials + toc_materials_all))
    parent_coverages: dict[str, dict[str, Any]] = {}
    plan_items: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        number = str(item.get("number") or "").strip()
        number_key = toc_number_key(number)
        title = str(item.get("title") or "").strip() or f"目录项-{index}"
        gap_id = f"GAP-{index:04d}"
        toc_materials = normalize_material_refs(item)
        wiki_materials = list(wiki_index.get(number) or [])
        index_materials = matching_materials_for_title(indexed_materials, title)
        candidate_materials = dedupe_materials(toc_materials + wiki_materials + index_materials)
        matched_material: dict[str, Any] | None = None
        alternative_materials: list[dict[str, Any]] = []
        structural = is_structural(item, items)
        fill_tasks: list[dict[str, Any]] = []
        required_inputs: list[dict[str, Any]] = []
        appendix_matches = matching_appendices(item, appendices)
        appendix_tasks: list[dict[str, Any]] = []
        decision = ""
        next_actions: list[str] = []
        coverage_role = ""
        covered_by_parent = ""
        usage = ""

        parent_key = number_key.split(".")[0] if "." in number_key else ""
        parent_coverage = parent_coverages.get(parent_key) if parent_key else None
        if parent_coverage:
            status = "matched"
            decision = "ready"
            usage = "covered_by_parent"
            coverage_role = "covered_by_parent"
            covered_by_parent = str(parent_coverage.get("id") or "")
            matched_materials = []
            gap_reason = f"已由父章节“{parent_coverage.get('title') or parent_key}”整章素材覆盖。"
            next_actions = ["s4_merge_material"]
        elif is_wind_master_item(item):
            wind_candidates = dedupe_materials(candidate_materials + all_wind_materials)
            matched_material, alternative_materials = pick_wind_master_material(wind_candidates)
            if matched_material:
                status = "matched"
                decision = "ready"
                usage = "chapter_master"
                coverage_role = "chapter_master"
                matched_materials = [matched_material]
                gap_reason = "整章素材可覆盖第3章及其子节。"
                next_actions = ["s4_merge_material"]
                parent_coverages[number_key] = {"id": gap_id, "title": title, "material": matched_material}
            else:
                status = "missing"
                decision = "material_required"
                usage = ""
                matched_materials = []
                gap_reason = "第3章需要整章风资源评估与机位排布方案 Word，但允许范围内未找到可用素材。"
                required_inputs.append({"type": "upload", "label": "上传第3章整章方案 Word 或选择已有素材"})
                next_actions = ["manual_upload", "select_material", "ignore"]
        elif appendix_matches:
            recommended_materials = dedupe_materials(candidate_materials + all_wind_materials)
            appendix_tasks = [
                build_appendix_task(appendix, recommended_materials_for_appendix(appendix, recommended_materials))
                for appendix in appendix_matches
            ]
            fill_tasks = [build_fill_task(item, appendix, gap_id) for appendix in appendix_matches]
            required_inputs.append({"type": "ai_fill", "label": "选择参考素材并填写空表"})
            status = "needs_input"
            decision = "fill_required"
            usage = "appendix_fill"
            matched_materials = []
            alternative_materials = recommended_materials
            gap_reason = "解析阶段已生成空副表/Word，需要进入 S3 发起填写任务。"
            next_actions = ["ai_fill_appendix", "select_reference_material", "manual_upload"]
        elif structural:
            status = "structural"
            decision = "ready"
            usage = "structural"
            matched_materials = []
            gap_reason = "结构性目录项，不直接要求素材。"
            next_actions = ["s4_merge_material"]
        elif candidate_materials:
            matched_material, alternative_materials = pick_material(candidate_materials, title)
            status = "matched"
            decision = "ready"
            usage = str((matched_material or {}).get("usage") or "section_merge")
            matched_materials = [matched_material] if matched_material else []
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
    return {
        "schemaVersion": SCHEMA_VERSION,
        "projectId": str(manifest.get("projectId") or ""),
        "projectName": str(manifest.get("projectName") or ""),
        "bidType": str(manifest.get("bidType") or "技术标"),
        "projectTurbineModel": project_turbine_model,
        "status": "ready",
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "summary": summary,
        "items": plan_items,
        "integrity": {
            "status": "passed" if summary["blockingCount"] == 0 else "blocked",
            "blockingCount": summary["blockingCount"],
            "checkedAt": now_iso(),
        },
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
                    "itemCount": len(plan["items"]),
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
