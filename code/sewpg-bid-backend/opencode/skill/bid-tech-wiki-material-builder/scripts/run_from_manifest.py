#!/usr/bin/env python3
"""Build the minimal material Wiki blueprint from a backend manifest."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


NODE_TITLES = [
    "01-素材总表",
    "02-章节映射表",
    "03-素材卡片",
    "04-待填写清单",
    "05-使用规则",
]


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"manifest must be a JSON object: {path}")
    return data


def md_escape(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", "<br>")


def material_title(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("name") or "未命名素材")


def tier_label(item: dict[str, Any]) -> str:
    tier = str(item.get("materialTier") or "").strip()
    identity_scope = str(item.get("identityScope") or "").strip()
    folder_path = str(item.get("folderPath") or item.get("path") or "")
    if tier == "customer" or identity_scope == "customer" or folder_path.startswith("客户素材"):
        return "客户素材"
    if tier == "project" or identity_scope == "project" or folder_path.startswith("项目素材"):
        return "项目素材"
    return "通用素材"


def identity_label(item: dict[str, Any]) -> str:
    scope = str(item.get("identityScope") or "general")
    if scope == "customer":
        return str(item.get("customerCanonicalName") or item.get("customerName") or "客户素材")
    if scope == "project":
        return str(item.get("projectCode") or item.get("projectId") or "项目素材")
    return "通用"


def first_headings(item: dict[str, Any], limit: int = 4) -> str:
    headings = item.get("headings") or []
    if not isinstance(headings, list) or not headings:
        return "未检测到 Heading"
    titles = [str(entry.get("title") or "") for entry in headings if isinstance(entry, dict)]
    return "；".join(title for title in titles[:limit] if title) or "未检测到 Heading"


def keywords(item: dict[str, Any]) -> str:
    values = item.get("keywords") or []
    if not isinstance(values, list) or not values:
        return material_title(item)
    return "、".join(str(value) for value in values[:6] if str(value).strip())


def source_path(item: dict[str, Any]) -> str:
    return str(item.get("path") or "/".join(part for part in [item.get("folderPath"), item.get("name")] if part)).strip("/")


def recommended_section(item: dict[str, Any]) -> str:
    return str(item.get("skeletonSection") or item.get("group") or "未明确")


def card_id(item: dict[str, Any]) -> str:
    raw_id = str(item.get("id") or material_title(item)).strip()
    return raw_id or material_title(item)


def build_inventory_node(items: list[dict[str, Any]], inventory: dict[str, Any], bid_type: str) -> dict[str, Any]:
    lines = [
        f"# 01-素材总表",
        "",
        f"- 标类：{bid_type}",
        f"- 素材数量：{len(items)}",
        f"- 原始材料总数：{inventory.get('sourceInventoryTotal') or inventory.get('total') or len(items)}",
        f"- 已解析 Word：{inventory.get('parsedDocxTotal', 0)}",
        "",
        "| 素材 | 层级 | AI身份 | 推荐用途 | 清洗稿 | Heading/表格 | 原始路径 |",
        "|---|---|---|---|---|---|---|",
    ]
    if not items:
        lines.append("| 待补料 | - | - | 当前未检出真实素材 | - | - | - |")
    for item in items:
        lines.append(
            "| {title} | {tier} | {identity} | {section} | {cleaned} | {heading} / 表格{tables} | `{path}` |".format(
                title=md_escape(material_title(item)),
                tier=md_escape(tier_label(item)),
                identity=md_escape(identity_label(item)),
                section=md_escape(recommended_section(item)),
                cleaned=md_escape(item.get("cleanedFileName") or ("可用" if item.get("hasCleanedWord") else "待清洗")),
                heading=md_escape(first_headings(item)),
                tables=int(item.get("tableCount") or 0),
                path=md_escape(source_path(item)),
            )
        )
    return node("01-素材总表", "\n".join(lines) + "\n", bid_type, ["素材总表", bid_type])


def build_mapping_node(items: list[dict[str, Any]], bid_type: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[recommended_section(item)].append(item)

    lines = [
        "# 02-章节映射表",
        "",
        "本表供缺口识别和生成标书按需读取。命中目录后先看候选卡片，再按使用方式决定整篇拼接、部分摘取、填表来源或附件引用。",
        "",
        "| 目录/章节需求 | 候选素材卡片 | 使用方式 | 原因 |",
        "|---|---|---|---|",
    ]
    if not grouped:
        lines.append("| 待补料 | - | 待上传素材 | 当前无真实素材可映射 |")
    for section, section_items in sorted(grouped.items()):
        titles = "、".join(material_title(item) for item in section_items[:8])
        usage = "部分摘取/整篇拼接/填表来源需在缺口处理页确认"
        reason = "由文件路径、标题、Heading、关键词推断"
        lines.append(f"| {md_escape(section)} | {md_escape(titles)} | {usage} | {reason} |")
    return node("02-章节映射表", "\n".join(lines) + "\n", bid_type, ["章节映射", bid_type])


def build_card_markdown(item: dict[str, Any], bid_type: str) -> str:
    aliases = item.get("customerAliases") or []
    alias_text = "、".join(str(value) for value in aliases if str(value).strip())
    paragraphs = item.get("paragraphs") if isinstance(item.get("paragraphs"), list) else []
    tables = item.get("tables") if isinstance(item.get("tables"), list) else []
    parse_error = str(item.get("parseError") or "")
    lines = [
        f"# {material_title(item)}",
        "",
        "## 素材来源",
        f"- material_id: {card_id(item)}",
        f"- path: {source_path(item)}",
        f"- tier: {tier_label(item)}",
        f"- cleaned_file_name: {item.get('cleanedFileName') or ''}",
        "",
        "## AI 检索身份",
        f"- identity_scope: {item.get('identityScope') or 'general'}",
        f"- material_scope: {item.get('materialScope') or item.get('identityScope') or 'general'}",
        f"- bid_type: {item.get('bidType') or bid_type}",
        f"- customer_id: {item.get('customerId') or ''}",
        f"- customer_name: {item.get('customerCanonicalName') or item.get('customerName') or ''}",
        f"- customer_aliases: {alias_text}",
        f"- project_id: {item.get('projectId') or ''}",
        f"- project_code: {item.get('projectCode') or ''}",
        "",
        "## 可以放在哪里",
        f"- 推荐章节：{recommended_section(item)}",
        f"- 关键词：{keywords(item)}",
        "- 使用方式：先作为候选素材；是否整篇拼接、摘取段落、填表来源或附件引用，由缺口处理阶段确认。",
        "",
        "## 内容线索",
        f"- Heading：{first_headings(item, 8)}",
        f"- 表格数量：{int(item.get('tableCount') or 0)}",
    ]
    if paragraphs:
        lines.append("- 正文摘录：")
        for paragraph in paragraphs[:6]:
            lines.append(f"  - {paragraph}")
    if tables:
        lines.append("- 表格线索：")
        for table in tables[:4]:
            lines.append(f"  - {table}")
    if parse_error:
        lines.append(f"- 解析风险：{parse_error}")
    lines.extend(
        [
            "",
            "## 待填写/部分使用提示",
            "- 若目录只需要本素材中的一段或一张表，不要整篇拼接，先在缺口处理页确认摘取范围。",
            "- 项目名称、业主、机型、容量、日期、保证值等项目字段必须在缺口处理页或填表任务中填写。",
            "",
            "## Merge 信息",
            f"- path: {source_path(item)}",
            f"- material_id: {card_id(item)}",
            f"- cleaned_file_name: {item.get('cleanedFileName') or ''}",
            f"- skeleton_section: {recommended_section(item)}",
            "- attach_mode: normal",
            "- shift: 0",
            f"- identity_scope: {item.get('identityScope') or 'general'}",
            f"- customer_id: {item.get('customerId') or ''}",
            f"- customer_name: {item.get('customerCanonicalName') or item.get('customerName') or ''}",
            f"- project_id: {item.get('projectId') or ''}",
            f"- project_code: {item.get('projectCode') or ''}",
        ]
    )
    return "\n".join(lines) + "\n"


def build_cards_node(items: list[dict[str, Any]], bid_type: str) -> dict[str, Any]:
    by_tier: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for item in items:
        by_tier[tier_label(item)][str(item.get("group") or recommended_section(item) or "未分类")].append(item)

    tier_children: list[dict[str, Any]] = []
    for tier in ("通用素材", "客户素材", "项目素材"):
        group_children: list[dict[str, Any]] = []
        for group, group_items in sorted(by_tier.get(tier, {}).items()):
            cards = [
                node(
                    material_title(item),
                    build_card_markdown(item, bid_type),
                    bid_type,
                    ["素材卡片", tier, group, bid_type],
                )
                for item in sorted(group_items, key=material_title)
            ]
            group_children.append(
                node(
                    group,
                    f"# {group}\n\n{tier}下的{group}素材卡片，共 {len(cards)} 张。\n",
                    bid_type,
                    ["素材分组", tier, group],
                    cards,
                )
            )
        if not group_children:
            group_children.append(node("待补料", f"# 待补料\n\n当前没有检出{tier}卡片。\n", bid_type, ["待补料", tier]))
        tier_children.append(
            node(
                tier,
                f"# {tier}\n\n按需加载的素材卡片入口。先读总表和章节映射，再加载具体卡片。\n",
                bid_type,
                ["素材层级", tier],
                group_children,
            )
        )
    return node("03-素材卡片", "# 03-素材卡片\n\n素材卡片按需加载，不承载完整原文，只记录定位、身份、用途和合并信息。\n", bid_type, ["素材卡片", bid_type], tier_children)


def build_fill_node(items: list[dict[str, Any]], bid_type: str) -> dict[str, Any]:
    candidates = []
    for item in items:
        text = " ".join(str(item.get(key) or "") for key in ("name", "title", "path", "group", "skeletonSection"))
        if any(token in text for token in ("参数", "保证", "附表", "空表", "报价", "授权", "日期", "容量", "项目")):
            candidates.append(item)

    lines = [
        "# 04-待填写清单",
        "",
        "本页只标记需要在缺口处理阶段确认或填写的内容。不要在 Wiki 阶段代填项目事实。",
        "",
        "| 待填写项 | 推荐来源 | 处理方式 |",
        "|---|---|---|",
        "| 项目名称/业主/场址/容量/机型 | 招标解析结果 + 项目素材 | 缺口处理页确认后替换 |",
        "| 技术保证值/商务保证值 | 招标空表 + 参数/保证类素材 | 选择来源文档后由填表任务写入 |",
        "| 日期/期限/授权代表/报价 | 商务或项目资料 | 人工确认或从指定来源填写 |",
    ]
    for item in candidates[:80]:
        lines.append(
            f"| {md_escape(material_title(item))} | `{md_escape(source_path(item))}` | 可作为填表来源或部分摘取来源 |"
        )
    return node("04-待填写清单", "\n".join(lines) + "\n", bid_type, ["待填写", bid_type])


def build_rules_node(items: list[dict[str, Any]], bid_type: str) -> dict[str, Any]:
    lines = [
        "# 05-使用规则",
        "",
        "## 读取顺序",
        "1. 先读 `01-素材总表` 判断素材库有什么。",
        "2. 再读 `02-章节映射表` 找候选素材。",
        "3. 只加载必要的 `03-素材卡片`。",
        "4. 先解决 `04-待填写清单`，再进入标书拼接。",
        "",
        "## 身份过滤",
        "- 通用素材可被同标类项目读取。",
        "- 客户素材必须命中 customer_id 或客户同义词。",
        "- 项目素材必须命中 project_id 或 project_code。",
        "- 身份不命中的素材不得用于缺口识别、填表或拼接。",
        "",
        "## 合并裁决",
        "- project > customer > general。",
        "- `override`：定制素材覆盖通用素材。",
        "- `append`：定制素材追加到通用素材后。",
        "- `reference`：只作为证据、附件或填表来源。",
        "- `exclude`：与项目条件冲突时剔除。",
        "",
        "## 禁止事项",
        "- 不编造项目参数、报价、日期、证书编号、保证值或业绩事实。",
        "- 不把只需一段内容的素材整篇拼接。",
        "- 不跳过待填写项直接生成最终标书。",
    ]
    return node("05-使用规则", "\n".join(lines) + "\n", bid_type, ["使用规则", bid_type])


def node(
    title: str,
    markdown: str,
    bid_type: str,
    tags: list[str] | None = None,
    children: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "markdownContent": markdown,
        "tags": tags or [bid_type],
        "applicableTypes": [bid_type],
        "children": children or [],
    }


def build_blueprint(manifest: dict[str, Any]) -> dict[str, Any]:
    bid_type = str(manifest.get("targetBidType") or "技术标")
    root_title = str(manifest.get("rootTitle") or f"{bid_type}Wiki（自动生成）")
    inventory = manifest.get("materialInventory") if isinstance(manifest.get("materialInventory"), dict) else {}
    items = [item for item in inventory.get("items") or [] if isinstance(item, dict)]
    return {
        "summary": f"已生成 {bid_type} 最小 Wiki：素材 {len(items)} 条，结构为素材总表/章节映射表/素材卡片/待填写清单/使用规则。",
        "rootTitle": root_title,
        "nodes": [
            build_inventory_node(items, inventory, bid_type),
            build_mapping_node(items, bid_type),
            build_cards_node(items, bid_type),
            build_fill_node(items, bid_type),
            build_rules_node(items, bid_type),
        ],
    }


def run_manifest(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    work_dir = Path(str(manifest.get("workDir") or manifest_path.parent)).expanduser()
    work_dir.mkdir(parents=True, exist_ok=True)
    output_file = Path(str(manifest.get("outputFile") or work_dir / "wiki_blueprint.json")).expanduser()
    output_file.parent.mkdir(parents=True, exist_ok=True)

    blueprint = build_blueprint(manifest)
    output_file.write_text(json.dumps(blueprint, ensure_ascii=False, indent=2), encoding="utf-8")

    inventory = manifest.get("materialInventory") if isinstance(manifest.get("materialInventory"), dict) else {}
    items = [item for item in inventory.get("items") or [] if isinstance(item, dict)]
    return {
        "schema_version": "bid-wiki-blueprint-v1",
        "skill": "bid-tech-wiki-material-builder",
        "outputFile": str(output_file),
        "summary": blueprint["summary"],
        "rootTitle": blueprint["rootTitle"],
        "materialCount": len(items),
        "nodeTitles": [str(node.get("title") or "") for node in blueprint.get("nodes") or []],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    response = run_manifest(load_json(args.manifest), args.manifest)
    print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
