#!/usr/bin/env python3
"""Export DB/API wiki nodes into the file-system wiki shape used by V2 TOC skill."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_API_BASE = "http://fastapi:8000"
WIKI_FILES = {
    "index": "index.md",
    "skeleton": "skeleton.md",
    "rules": "rules.md",
    "synonyms": "synonyms.md",
}
IDENTITY_FIELDS = {
    "material_id",
    "identity_scope",
    "material_scope",
    "bid_type",
    "customer_id",
    "customer_name",
    "customer_aliases",
    "project_id",
    "project_code",
}


def fetch_json(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise RuntimeError(f"API returned non-object JSON: {url}")
    return data


def api_get(api_base: str, params: dict[str, str], timeout: float) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    return fetch_json(f"{api_base.rstrip('/')}/api/materials/wiki?{query}", timeout)


def iter_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        out.append(node)
        out.extend(iter_tree(list(node.get("children") or [])))
    return out


def safe_filename(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


def parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    out: dict[str, Any] = {}
    for raw_line in text[3:end].strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def parse_merge_fields(text: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("- ") or ":" not in line:
            continue
        key, _, value = line[2:].partition(":")
        key = key.strip()
        if key not in {
            "path",
            "scope",
            "category",
            "skeleton_section",
            "skeleton_level",
            "material_level_range",
            "heading_count",
            "shift",
            "attach_mode",
            "condition",
            "deprecated",
        } | IDENTITY_FIELDS:
            continue
        value = value.strip().strip('"').strip("'")
        if value.lower() in {"true", "false"}:
            fields[key] = value.lower() == "true"
        elif re.fullmatch(r"-?\d+", value):
            fields[key] = int(value)
        else:
            fields[key] = value
    return fields


def infer_scope(selected: dict[str, Any], merge_fields: dict[str, Any]) -> str:
    explicit = str(merge_fields.get("scope") or "").strip()
    if explicit:
        return explicit
    text = " ".join(
        [
            str(selected.get("title") or ""),
            str(selected.get("path") or ""),
            " ".join(str(item) for item in selected.get("tags") or []),
        ]
    )
    if "定制" in text or "项目材料" in text:
        return "定制"
    return "通用"


def infer_category(selected: dict[str, Any], merge_fields: dict[str, Any]) -> str:
    explicit = str(merge_fields.get("category") or "").strip()
    if explicit:
        return explicit
    ignored = {"素材卡片", "技术标", "商务标", "通用", "通用素材", "客户素材", "项目素材", "项目材料", "定制"}
    for tag in selected.get("tags") or []:
        tag_text = str(tag or "").strip()
        if tag_text and tag_text not in ignored:
            return tag_text
    path = str(selected.get("path") or "")
    parts = [item for item in path.split("/") if item]
    return parts[-2] if len(parts) >= 2 else ""


def extract_section_from_title(title: str) -> str:
    match = re.search(r"(?<!\d)(\d+(?:\.\d+){0,4})(?!\d)", title)
    if match:
        return match.group(1)
    if "前言" in title or "投标说明函" in title:
        return "前言"
    if "附表" in title:
        return "附表"
    return "未明确"


def normalize_card_frontmatter(selected: dict[str, Any]) -> dict[str, Any]:
    markdown = str(selected.get("markdownContent") or "")
    frontmatter = parse_frontmatter(markdown)
    merge_fields = {**frontmatter, **parse_merge_fields(markdown)}
    title = str(selected.get("title") or "")
    section = str(merge_fields.get("skeleton_section") or "").strip() or extract_section_from_title(title)
    heading_count = merge_fields.get("heading_count", 0)
    shift = merge_fields.get("shift", 0)
    try:
        heading_count = int(heading_count)
    except (TypeError, ValueError):
        heading_count = 0
    try:
        shift = int(shift)
    except (TypeError, ValueError):
        shift = 0
    return {
        "path": str(merge_fields.get("path") or selected.get("path") or ""),
        "scope": infer_scope(selected, merge_fields),
        "category": infer_category(selected, merge_fields),
        "material_id": str(merge_fields.get("material_id") or ""),
        "identity_scope": str(merge_fields.get("identity_scope") or "general"),
        "material_scope": str(merge_fields.get("material_scope") or merge_fields.get("identity_scope") or "general"),
        "bid_type": str(merge_fields.get("bid_type") or ""),
        "customer_id": str(merge_fields.get("customer_id") or ""),
        "customer_name": str(merge_fields.get("customer_name") or ""),
        "customer_aliases": str(merge_fields.get("customer_aliases") or ""),
        "project_id": str(merge_fields.get("project_id") or ""),
        "project_code": str(merge_fields.get("project_code") or ""),
        "skeleton_section": section,
        "skeleton_level": str(merge_fields.get("skeleton_level") or "section"),
        "material_level_range": str(merge_fields.get("material_level_range") or "none"),
        "heading_count": heading_count,
        "shift": shift,
        "attach_mode": str(merge_fields.get("attach_mode") or "normal"),
        "condition": str(merge_fields.get("condition") or ""),
        "deprecated": bool(merge_fields.get("deprecated") or False),
    }


def render_frontmatter(data: dict[str, Any]) -> str:
    lines = ["---"]
    for key in [
        "path",
        "scope",
        "category",
        "material_id",
        "identity_scope",
        "material_scope",
        "bid_type",
        "customer_id",
        "customer_name",
        "customer_aliases",
        "project_id",
        "project_code",
        "skeleton_section",
        "skeleton_level",
        "material_level_range",
        "heading_count",
        "shift",
        "attach_mode",
        "condition",
        "deprecated",
    ]:
        value = data.get(key)
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value if value is not None else "")
        lines.append(f"{key}: {json.dumps(rendered, ensure_ascii=False) if isinstance(value, str) else rendered}")
    lines.append("---")
    return "\n".join(lines)


def classify_root_file(title: str) -> str | None:
    lowered = title.lower()
    if "速查索引" in title or "index" in lowered:
        return WIKI_FILES["index"]
    if "目录骨架" in title or "skeleton" in lowered:
        return WIKI_FILES["skeleton"]
    if "装配规则" in title or "rules" in lowered:
        return WIKI_FILES["rules"]
    if "同义词" in title or "synonyms" in lowered:
        return WIKI_FILES["synonyms"]
    return None


def export_wiki(api_base: str, bid_type: str, out_dir: Path, timeout: float) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cards_dir = out_dir / "卡片"
    cards_dir.mkdir(parents=True, exist_ok=True)

    root_payload = api_get(api_base, {"bidType": bid_type}, timeout)
    tree = list(root_payload.get("tree") or [])
    tree_nodes = iter_tree(tree)
    selected_nodes: list[dict[str, Any]] = []

    for node in tree_nodes:
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        payload = api_get(api_base, {"nodeId": node_id, "bidType": bid_type}, timeout)
        selected = payload.get("selectedNode")
        if isinstance(selected, dict):
            selected_nodes.append(selected)

    root_file_counts: dict[str, int] = {name: 0 for name in WIKI_FILES.values()}
    card_count = 0
    for selected in selected_nodes:
        title = str(selected.get("title") or "").strip()
        markdown = str(selected.get("markdownContent") or f"# {title}\n")
        if not title:
            continue

        root_file = classify_root_file(title)
        if root_file:
            (out_dir / root_file).write_text(markdown.strip() + "\n", encoding="utf-8")
            root_file_counts[root_file] += 1
            continue

        frontmatter = normalize_card_frontmatter(selected)
        file_name = safe_filename(title, f"card-{card_count + 1}") + ".md"
        card_path = cards_dir / file_name
        card_path.write_text(
            f"{render_frontmatter(frontmatter)}\n\n{markdown.strip()}\n",
            encoding="utf-8",
        )
        card_count += 1

    defaults = {
        "index.md": f"# {bid_type}素材索引\n\n由后端 API 导出，供目录生成 skill 读取。\n",
        "skeleton.md": f"# {bid_type}目录骨架\n\n素材卡片 frontmatter 中的 skeleton_section 为目录挂载依据。\n",
        "rules.md": f"# {bid_type}装配规则\n\n优先使用模板骨架，叠加招标要求与素材卡片建议。\n",
        "synonyms.md": f"# {bid_type}同义词\n\n后续由素材库维护章节词、业主词和文件名词的映射。\n",
    }
    for file_name, content in defaults.items():
        path = out_dir / file_name
        if not path.exists():
            path.write_text(content, encoding="utf-8")

    return {
        "apiBase": api_base,
        "bidType": bid_type,
        "outDir": str(out_dir),
        "treeNodeCount": len(tree_nodes),
        "selectedNodeCount": len(selected_nodes),
        "cardCount": card_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--bid-type", default="技术标")
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    try:
        result = export_wiki(
            api_base=str(args.api_base or DEFAULT_API_BASE),
            bid_type=str(args.bid_type or "技术标"),
            out_dir=Path(args.out),
            timeout=float(args.timeout or 20.0),
        )
    except Exception as exc:
        print(f"export_wiki_from_api failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
