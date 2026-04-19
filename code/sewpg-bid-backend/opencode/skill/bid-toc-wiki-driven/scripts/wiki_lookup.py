#!/usr/bin/env python3
"""wiki_lookup.py — 查询 wiki 卡片 frontmatter 的 merge 元数据

用法：
    python3 wiki_lookup.py --wiki <wiki路径> --name "技术标-叶片专题"
    python3 wiki_lookup.py --wiki <wiki路径> --all          # 全量导出 JSON
"""
import argparse
import json
import sys
from pathlib import Path


def parse_frontmatter(text: str) -> dict:
    """手工解析 YAML frontmatter（避免依赖 PyYAML/python-frontmatter）。"""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    body = text[3:end].strip()
    out = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        v = v.strip().strip('"').strip("'")
        if v.lower() in ("true", "false"):
            out[k.strip()] = v.lower() == "true"
        elif v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
            out[k.strip()] = int(v)
        else:
            out[k.strip()] = v
    return out


def find_card(wiki_root: Path, name: str) -> Path | None:
    cards = wiki_root / "卡片"
    for p in cards.rglob("*.md"):
        if p.stem == name:
            return p
    return None


def lookup(wiki_root: Path, name: str) -> dict:
    card = find_card(wiki_root, name)
    if card is None:
        return {"name": name, "found": False, "error": "card not found"}
    text = card.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    return {
        "name": name,
        "found": True,
        "card_path": str(card),
        "path": fm.get("path", ""),
        "scope": fm.get("scope", ""),
        "category": fm.get("category", ""),
        "skeleton_section": fm.get("skeleton_section", "未明确"),
        "skeleton_level": fm.get("skeleton_level", "unknown"),
        "material_level_range": fm.get("material_level_range", "none"),
        "heading_count": fm.get("heading_count", 0),
        "shift": fm.get("shift", 0),
        "attach_mode": fm.get("attach_mode", "normal"),
        "condition": fm.get("condition", ""),
        "deprecated": fm.get("deprecated", False),
    }


def all_cards(wiki_root: Path) -> list[dict]:
    cards = wiki_root / "卡片"
    out = []
    for p in cards.rglob("*.md"):
        out.append(lookup(wiki_root, p.stem))
    return out


def section_to_level(section) -> int:
    """skeleton_section 拆点数得 H 级。'1.3'→2, '5.8.1'→3, '5.9.2.1'→4。
    特殊值：'未明确' / '附表' / '' → 0（兜底，主流程决定归位）。
    section 可能是 int（如 "5"），也可能是字符串。"""
    s = str(section or "").strip()
    if not s or s in ("未明确", "附表"):
        return 0
    parts = [p for p in s.split(".") if p.isdigit()]
    return len(parts) if parts else 0


def strip_prefix(name: str) -> str:
    """素材名去常见前缀，便于做目录显示文本。"""
    for prefix in ("技术标-",):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def list_by_section(wiki_root: Path) -> list[dict]:
    """按 skeleton_section 升序导出全部素材，输出目录条目候选。
    每条字段：section / level / display_name / source_name / 其他 frontmatter。"""
    items = []
    for c in all_cards(wiki_root):
        if not c.get("found"):
            continue
        if c.get("deprecated"):
            continue
        section = str(c.get("skeleton_section", ""))
        items.append({
            "section": section,
            "level": section_to_level(section),
            "display_name": strip_prefix(c["name"]),
            "source_name": c["name"],
            "scope": c.get("scope", ""),
            "category": c.get("category", ""),
            "skeleton_level": c.get("skeleton_level", "unknown"),
            "heading_count": c.get("heading_count", 0),
            "shift": c.get("shift", 0),
            "attach_mode": c.get("attach_mode", "normal"),
            "condition": c.get("condition", ""),
            "path": c.get("path", ""),
        })

    def sort_key(it):
        s = str(it["section"])
        if not s or s in ("未明确", "附表"):
            return (99, 99, 99, 99, 99, it["display_name"])
        parts = s.split(".")
        nums = []
        for p in parts:
            try:
                nums.append(int(p))
            except ValueError:
                nums.append(98)
        nums = (nums + [0, 0, 0, 0, 0])[:5]
        return tuple(nums) + (it["display_name"],)

    items.sort(key=sort_key)
    return items


def level_to_h(level: str, default: int = 3) -> int:
    """skeleton_level → docx Heading 级（1-6）"""
    mapping = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5, "L6": 6}
    if level == "L_attach":
        return -1  # 附件标记，不占主编号
    return mapping.get(level, default)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", required=True, help="wiki 根目录（含卡片/ 子目录）")
    ap.add_argument("--name", help="素材名（去扩展名）")
    ap.add_argument("--all", action="store_true", help="导出全部卡片元数据")
    ap.add_argument("--list-by-section", action="store_true",
                    help="按 skeleton_section 升序导出目录候选条目（一对一映射素材）")
    args = ap.parse_args()

    wiki = Path(args.wiki).expanduser().resolve()
    if not (wiki / "卡片").exists():
        print(json.dumps({"error": f"wiki/卡片 not found at {wiki}"}, ensure_ascii=False))
        sys.exit(1)

    if args.list_by_section:
        result = list_by_section(wiki)
    elif args.all:
        result = all_cards(wiki)
    elif args.name:
        result = lookup(wiki, args.name)
    else:
        ap.error("--name, --all, or --list-by-section required")

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
