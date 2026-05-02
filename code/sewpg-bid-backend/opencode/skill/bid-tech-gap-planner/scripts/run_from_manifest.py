#!/usr/bin/env python3
"""Build bid-tech-gap-plan-v1 from confirmed TOC and parse artifacts."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
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
            output.append({"id": ref, "path": ref, "usage": "both", "matchReason": "目录生成已引用素材"})
            continue
        if not isinstance(ref, dict):
            continue
        output.append(
            {
                "id": str(ref.get("id") or ref.get("material_id") or f"MAT-{index}"),
                "path": str(ref.get("docx") or ref.get("path") or ""),
                "usage": str(ref.get("usage") or "both"),
                "matchReason": str(ref.get("reason") or "目录生成已引用素材"),
                "confidence": float(ref.get("confidence") or 0.85),
            }
        )
    return output


def needs_fill_task(item: dict[str, Any], appendices: list[dict[str, Any]]) -> bool:
    text = " ".join(
        str(item.get(key) or "")
        for key in ("title", "annotation", "reason", "source")
    )
    return bool(appendices) and (
        "附表" in text
        or "空表" in text
        or "性能" in text
        or "保证" in text
        or "新增" in text
    )


def build_fill_task(item: dict[str, Any], appendices: list[dict[str, Any]], gap_id: str) -> dict[str, Any]:
    appendix = appendices[0] if appendices else {}
    title = str(item.get("title") or "待填写内容")
    return {
        "id": f"FILL-{gap_id}",
        "skill": "bid-tech-table-filler",
        "status": "pending",
        "title": f"填写{title}",
        "blankSource": {
            "id": str(appendix.get("id") or appendix.get("title") or "APP-UNKNOWN"),
            "title": str(appendix.get("title") or "招标附表空表"),
            "sourceFile": str(appendix.get("sourceFile") or appendix.get("source_file") or ""),
        },
        "requiredReferences": ["素材库文件", "招标解析字段"],
    }


def build_gap_plan(manifest: dict[str, Any]) -> dict[str, Any]:
    toc = load_json(Path(str(manifest["tocJsonPath"])))
    parse_result_path = Path(str(manifest.get("parseResultPath") or ""))
    parse_result = load_json(parse_result_path) if parse_result_path.exists() else {}
    items = toc_items(toc)
    appendices = appendices_from_parse(parse_result)
    plan_items: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        number = str(item.get("number") or "").strip()
        title = str(item.get("title") or "").strip() or f"目录项-{index}"
        gap_id = f"GAP-{index:04d}"
        matched_materials = normalize_material_refs(item)
        structural = is_structural(item, items)
        fill_tasks: list[dict[str, Any]] = []
        required_inputs: list[dict[str, Any]] = []

        if matched_materials:
            status = "matched"
            gap_reason = ""
        elif structural:
            status = "structural"
            gap_reason = "结构性目录项，不直接要求素材。"
        elif needs_fill_task(item, appendices):
            status = "needs_input"
            gap_reason = "目录项缺少可直接拼接素材，可通过 AI 填写招标附表/空表补齐。"
            fill_tasks.append(build_fill_task(item, appendices, gap_id))
            required_inputs.append({"type": "ai_fill", "label": "选择参考素材并填写空表"})
        else:
            status = "missing"
            gap_reason = "目录项未匹配到素材库 Wiki 或补料记录。"
            required_inputs.append({"type": "upload", "label": "上传客户资料或选择已有素材"})

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
                "priority": "high" if status in {"needs_input", "missing"} else "medium",
                "matchedMaterials": matched_materials,
                "requiredInputs": required_inputs,
                "fillTasks": fill_tasks,
                "resolvedArtifacts": [],
                "reviewNotes": [],
                "gapReason": gap_reason,
            }
        )

    summary = summarize(plan_items)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "projectId": str(manifest.get("projectId") or ""),
        "projectName": str(manifest.get("projectName") or ""),
        "bidType": str(manifest.get("bidType") or "技术标"),
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
    return {
        "totalTocItems": len(items),
        "matchedCount": counts.get("matched", 0),
        "missingCount": counts.get("missing", 0) + counts.get("needs_input", 0),
        "resolvedCount": counts.get("resolved", 0),
        "ignoredCount": counts.get("ignored", 0),
        "structuralCount": counts.get("structural", 0),
        "fillableTaskCount": sum(len(item.get("fillTasks") or []) for item in items),
        "blockingCount": counts.get("missing", 0) + counts.get("needs_input", 0) + counts.get("filling", 0),
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
