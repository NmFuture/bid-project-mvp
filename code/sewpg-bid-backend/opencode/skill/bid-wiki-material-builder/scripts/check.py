#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wiki 一致性检查：扫素材库 vs index.md vs 卡片目录
报差异不自动修，由人+LLM 决策。
"""
from pathlib import Path
import re

WIKI_DIR = Path(__file__).resolve().parent.parent  # wiki/scripts/ → wiki/
ROOT = WIKI_DIR.parent
MATERIAL_DIRS = [ROOT / "投标资料库-通用", ROOT / "投标资料库-定制"]
EXTS = {".docx", ".pdf", ".xlsx"}


def scan_materials():
    files = set()
    for base in MATERIAL_DIRS:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in EXTS and not p.name.startswith("."):
                files.add(p.relative_to(ROOT).as_posix())
    return files


def scan_cards():
    cards = {}
    card_root = WIKI_DIR / "卡片"
    if not card_root.exists():
        return cards
    for p in card_root.rglob("*.md"):
        if p.name.startswith("."):
            continue
        text = p.read_text(encoding="utf-8")
        m = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL | re.MULTILINE)
        path_field = None
        if m:
            for line in m.group(1).splitlines():
                if line.strip().startswith("path:"):
                    path_field = line.split(":", 1)[1].strip()
                    break
        cards[p.relative_to(WIKI_DIR).as_posix()] = path_field
    return cards


def scan_index():
    idx = WIKI_DIR / "index.md"
    if not idx.exists():
        return set()
    names = set()
    for line in idx.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*([^|]+?)\s*\|", line.strip())
        if m:
            name = m.group(1).strip()
            if name and name != "素材名" and not name.startswith("---"):
                names.add(name)
    return names


def main():
    materials = scan_materials()
    cards = scan_cards()
    idx_names = scan_index()
    issues = 0

    card_paths = {p for p in cards.values() if p}
    missing_card = materials - card_paths
    orphan_card = {c for c, p in cards.items() if p and p not in materials}

    material_names = {Path(p).stem for p in materials}
    card_names = {Path(c).stem for c in cards}
    missing_idx = (material_names & card_names) - idx_names
    orphan_idx = idx_names - material_names

    if missing_card:
        print(f"[缺卡片] 素材库有文件但卡片 path 字段不匹配（共 {len(missing_card)}）：")
        for p in sorted(missing_card):
            print(f"  - {p}")
        issues += len(missing_card)

    if orphan_card:
        print(f"\n[孤儿卡片] 卡片 path 指向的素材不存在（共 {len(orphan_card)}）：")
        for c in sorted(orphan_card):
            print(f"  - {c} → path: {cards[c]}")
        issues += len(orphan_card)

    if missing_idx:
        print(f"\n[缺 index 条目] 素材和卡片都有但 index.md 没列出（共 {len(missing_idx)}）：")
        for n in sorted(missing_idx):
            print(f"  - {n}")
        issues += len(missing_idx)

    if orphan_idx:
        print(f"\n[index 孤儿] index.md 有条目但素材库找不到（共 {len(orphan_idx)}）：")
        for n in sorted(orphan_idx):
            print(f"  - {n}")
        issues += len(orphan_idx)

    print(f"\n汇总：素材 {len(materials)}、卡片 {len(cards)}、index 条目 {len(idx_names)}；问题 {issues}。")
    return 0 if issues == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
