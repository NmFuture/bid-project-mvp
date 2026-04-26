#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Initialize or refresh an LLM Wiki from a bid material library."""
from __future__ import annotations

import argparse
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    from docx import Document
except ImportError:
    Document = None


SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_WIKI = SKILL_DIR / "assets" / "wiki-template"
CARD_ROOT_NAME = "卡片"
SCOPE_DIRS = ("投标资料库-通用", "投标资料库-定制")
CATEGORY_ORDER = [
    "标前概述",
    "投标函件",
    "总体方案",
    "设备全周期",
    "专项技术",
    "风资源评估",
    "风机子系统",
    "环境适应性",
    "技术标准",
    "交付验收",
    "项目数据",
]


@dataclass
class Material:
    name: str
    rel_path: str
    scope: str
    category: str
    headings: list[tuple[int, str]]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        out[key.strip()] = value.strip().strip('"')
    return out


def extract_keywords(card_text: str, fallback: str) -> str:
    m = re.search(r"主关键词[:：]\s*(.+)", card_text)
    if m:
        return m.group(1).strip()
    clean = re.sub(r"^技术标-", "", fallback)
    clean = re.sub(r"(专题|方案|概述|报告|情况|一览表)$", "", clean)
    return clean


def extract_trigger(card_text: str) -> str:
    m = re.search(r"## 必选 / 条件\s*\n(.+?)(?:\n## |\Z)", card_text, re.DOTALL)
    if not m:
        return "待判定"
    lines = [line.strip("- \t") for line in m.group(1).splitlines() if line.strip()]
    return lines[0] if lines else "待判定"


def template_cards_by_name() -> dict[str, tuple[Path, str, dict[str, str]]]:
    cards: dict[str, tuple[Path, str, dict[str, str]]] = {}
    root = TEMPLATE_WIKI / CARD_ROOT_NAME
    if not root.exists():
        return cards
    for path in root.rglob("*.md"):
        text = read_text(path)
        fm = parse_frontmatter(text)
        name = fm.get("name") or path.stem
        cards[name] = (path, text, fm)
    return cards


def heading_stats(docx_path: Path) -> list[tuple[int, str]]:
    if Document is None:
        return []
    try:
        doc = Document(str(docx_path))
    except Exception:
        return []
    out: list[tuple[int, str]] = []
    for para in doc.paragraphs:
        style = para.style.name if para.style else ""
        if not style.startswith("Heading"):
            continue
        suffix = style[len("Heading"):].strip()
        if not suffix.isdigit():
            continue
        text = para.text.strip()
        if text:
            out.append((int(suffix), text))
    return out


def material_level_range(headings: list[tuple[int, str]]) -> str:
    if not headings:
        return "none"
    levels = sorted({level for level, _ in headings})
    return f"L{levels[0]}-L{levels[-1]}"


def format_heading_tree(headings: list[tuple[int, str]]) -> str:
    if not headings:
        return ""
    min_level = min(level for level, _ in headings)
    lines = []
    for level, title in headings:
        indent = " " * (4 + (level - min_level) * 2)
        lines.append(f"{indent}L{level}  {title}")
    return "\n".join(lines)


def render_merge_section(material: Material, fm: dict[str, str]) -> str:
    section = fm.get("skeleton_section", "未明确")
    skeleton_level = fm.get("skeleton_level", "unknown")
    shift = fm.get("shift", "0")
    level_range = material_level_range(material.headings)
    lines = [
        "<!-- MERGE_INFO_START -->",
        "",
        "## Merge 信息",
        f"- 投标骨架章节号：**{section}**",
        f"- 骨架生成层级：**{skeleton_level}**",
    ]
    if material.headings:
        lines.append(f"- 素材内部层级：{level_range}（共 {len(material.headings)} 条 Heading）")
    else:
        lines.append("- 素材内部层级：none（无 Heading，整段作为正文贴入）")
    lines.append(f"- 升降级：{shift}")
    tree = format_heading_tree(material.headings)
    if tree:
        lines.extend(["", "### 素材内部 Heading 树", "```", tree, "```"])
    lines.extend(["", "<!-- MERGE_INFO_END -->"])
    return "\n".join(lines)


def infer_category(scope: str, rel_parts: tuple[str, ...], name: str, template_fm: dict[str, str] | None) -> str:
    if template_fm and template_fm.get("category"):
        return template_fm["category"]
    if scope == "定制":
        return "项目数据"
    joined = "/".join(rel_parts)
    for category in CATEGORY_ORDER:
        if category != "项目数据" and category in joined:
            return category
    if "封面" in name:
        return "标前概述"
    if "投标说明函" in name or "承诺函" in name:
        return "投标函件"
    if "技术标准" in name:
        return "技术标准"
    if "交付" in name or "验收" in name:
        return "交付验收"
    return "专项技术"


def scan_materials(root: Path, templates: dict[str, tuple[Path, str, dict[str, str]]]) -> list[Material]:
    materials: list[Material] = []
    for scope_dir in SCOPE_DIRS:
        base = root / scope_dir
        if not base.exists():
            continue
        scope = "通用" if scope_dir.endswith("通用") else "定制"
        for docx_path in sorted(base.rglob("*.docx")):
            if docx_path.name.startswith("~$") or "archive" in docx_path.parts:
                continue
            rel = docx_path.relative_to(root).as_posix()
            name = docx_path.stem
            template_fm = templates.get(name, (None, "", {}))[2]
            rel_parts = docx_path.relative_to(base).parts
            category = infer_category(scope, rel_parts, name, template_fm)
            materials.append(Material(name, rel, scope, category, heading_stats(docx_path)))
    return materials


def seed_base_files(wiki_dir: Path, seed_cards: bool) -> None:
    wiki_dir.mkdir(parents=True, exist_ok=True)
    for name in ("CLAUDE.md", "rules.md", "skeleton.md", "synonyms.md", "log.md"):
        src = TEMPLATE_WIKI / name
        dst = wiki_dir / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
    scripts_src = TEMPLATE_WIKI / "scripts"
    scripts_dst = wiki_dir / "scripts"
    if scripts_src.exists():
        scripts_dst.mkdir(parents=True, exist_ok=True)
        for src in scripts_src.glob("*.py"):
            dst = scripts_dst / src.name
            if not dst.exists():
                shutil.copy2(src, dst)
    if seed_cards:
        src_cards = TEMPLATE_WIKI / CARD_ROOT_NAME
        dst_cards = wiki_dir / CARD_ROOT_NAME
        if src_cards.exists() and not dst_cards.exists():
            shutil.copytree(src_cards, dst_cards)


def render_card(material: Material, template_text: str | None) -> str:
    if template_text:
        fm = parse_frontmatter(template_text)
        text = template_text
        text = re.sub(r"^path:\s*.*$", f"path: {material.rel_path}", text, flags=re.MULTILINE)
        text = re.sub(r"^scope:\s*.*$", f"scope: {material.scope}", text, flags=re.MULTILINE)
        text = re.sub(r"^category:\s*.*$", f"category: {material.category}", text, flags=re.MULTILINE)
        text = re.sub(r"^material_level_range:\s*.*$", f"material_level_range: {material_level_range(material.headings)}", text, flags=re.MULTILINE)
        text = re.sub(r"^heading_count:\s*.*$", f"heading_count: {len(material.headings)}", text, flags=re.MULTILINE)
        merge = render_merge_section(material, fm)
        text = re.sub(
            r"<!-- MERGE_INFO_START -->.*?<!-- MERGE_INFO_END -->",
            merge,
            text,
            flags=re.DOTALL,
        )
        return text if text.endswith("\n") else text + "\n"

    keywords = extract_keywords("", material.name)
    return f"""---
name: {material.name}
path: {material.rel_path}
scope: {material.scope}
category: {material.category}
deprecated: false
skeleton_section: "未明确"
skeleton_level: unknown
material_level_range: {material_level_range(material.headings)}
heading_count: {len(material.headings)}
shift: 0
attach_mode: normal
---
# {material.name}

## 该填进什么章节
- 主关键词：{keywords}
- 同义词：无
- 典型父章节：待判定

## 适用条件
- 机型：所有
- 场址：所有
- 业主：所有
- 地块：所有

## 必选 / 条件
待判定

## 关联素材
- 无

## 可替换字段
无

## 注意
待补充

<!-- MERGE_INFO_START -->

## Merge 信息
- 投标骨架章节号：**未明确**
- 骨架生成层级：**unknown**
- 素材内部层级：{material_level_range(material.headings)}
- 升降级：无

<!-- MERGE_INFO_END -->
"""


def card_path(wiki_dir: Path, material: Material) -> Path:
    return wiki_dir / CARD_ROOT_NAME / material.scope / material.category / f"{material.name}.md"


def upsert_cards(
    wiki_dir: Path,
    materials: list[Material],
    templates: dict[str, tuple[Path, str, dict[str, str]]],
    overwrite: bool,
) -> list[Path]:
    changed: list[Path] = []
    for material in materials:
        dst = card_path(wiki_dir, material)
        if dst.exists() and not overwrite:
            continue
        template_text = templates.get(material.name, (None, None, {}))[1]
        write_text(dst, render_card(material, template_text))
        changed.append(dst)
    return changed


def collect_cards(wiki_dir: Path) -> list[tuple[Path, str, dict[str, str]]]:
    root = wiki_dir / CARD_ROOT_NAME
    cards: list[tuple[Path, str, dict[str, str]]] = []
    if not root.exists():
        return cards
    for path in sorted(root.rglob("*.md")):
        text = read_text(path)
        cards.append((path, text, parse_frontmatter(text)))
    return cards


def render_index(wiki_dir: Path) -> str:
    rows = []
    for path, text, fm in collect_cards(wiki_dir):
        name = fm.get("name") or path.stem
        scope = fm.get("scope", "未明确")
        category = fm.get("category", "未明确")
        keywords = extract_keywords(text, name)
        trigger = extract_trigger(text)
        rel_card = path.relative_to(wiki_dir).as_posix()
        rows.append((scope, category, name, keywords, trigger, rel_card))

    order = {cat: i for i, cat in enumerate(CATEGORY_ORDER)}
    rows.sort(key=lambda r: (0 if r[0] == "通用" else 1, order.get(r[1], 99), r[2]))

    lines = [
        f"# 投标素材速查（{len(rows)} 条）",
        "",
        "> L1 必读文件。先在“主关键词”列做子串匹配；失配时查 `synonyms.md`，再失配用语义兜底。",
        "> 约定：素材路径见对应卡片的 `path` 字段。",
        "",
        "| 素材名 | 分类 | 主关键词 | 触发 | 卡片 |",
        "|---|---|---|---|---|",
    ]
    for scope, category, name, keywords, trigger, rel_card in rows:
        lines.append(f"| {name} | {scope}/{category} | {keywords} | {trigger} | [→]({rel_card}) |")
    lines.append("")
    return "\n".join(lines)


def append_log(wiki_dir: Path, message: str) -> None:
    log = wiki_dir / "log.md"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"\n## [{stamp}] bootstrap\n\n- {message}\n"
    if log.exists():
        log.write_text(read_text(log).rstrip() + line, encoding="utf-8")
    else:
        write_text(log, f"# Wiki 维护日志\n{line}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("material_root", help="素材库根目录，包含 投标资料库-通用 / 投标资料库-定制")
    parser.add_argument("--wiki-dir", help="wiki 输出目录；默认 <material_root>/wiki")
    parser.add_argument("--seed-template-cards", action="store_true", help="首次初始化时复制本 skill 附带的示例卡片")
    parser.add_argument("--overwrite-cards", action="store_true", help="用扫描结果覆盖同名卡片")
    args = parser.parse_args()

    root = Path(args.material_root).expanduser().resolve()
    wiki_dir = Path(args.wiki_dir).expanduser().resolve() if args.wiki_dir else root / "wiki"
    if root.name == "wiki" and not args.wiki_dir:
        wiki_dir = root
        root = root.parent

    templates = template_cards_by_name()
    seed_base_files(wiki_dir, args.seed_template_cards)
    materials = scan_materials(root, templates)
    changed = upsert_cards(wiki_dir, materials, templates, args.overwrite_cards)
    write_text(wiki_dir / "index.md", render_index(wiki_dir))
    append_log(wiki_dir, f"扫描素材 {len(materials)} 份，写入/覆盖卡片 {len(changed)} 张，刷新 index.md。")

    print(f"素材库根目录: {root}")
    print(f"wiki 目录: {wiki_dir}")
    print(f"扫描素材: {len(materials)}")
    print(f"写入/覆盖卡片: {len(changed)}")
    print("下一步: 编辑 skeleton.md/rules.md 后运行 wiki/scripts/extract_headings.py --audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
