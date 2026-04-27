#!/usr/bin/env python3
"""wiki_lookup.py — 查询 wiki 卡片 frontmatter 的 merge 元数据

用法：
    python3 wiki_lookup.py --wiki <wiki路径> --name "技术标-叶片专题"
    python3 wiki_lookup.py --wiki <wiki路径> --all          # 全量导出 JSON
"""
import argparse
import json
import re
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


def extract_internal_headings(text: str) -> list[dict]:
    """从卡片 Merge 信息中的“素材内部 Heading 树”代码块提取标题。"""
    marker = "### 素材内部 Heading 树"
    start = text.find(marker)
    if start < 0:
        return []
    fence_start = text.find("```", start)
    if fence_start < 0:
        return []
    fence_end = text.find("```", fence_start + 3)
    if fence_end < 0:
        return []

    out = []
    for raw in text[fence_start + 3:fence_end].splitlines():
        line = raw.strip()
        if not line.startswith("L") or " " not in line:
            continue
        level_token, _, title = line.partition(" ")
        if not level_token[1:].isdigit():
            continue
        title = title.strip()
        if title:
            out.append({"level": int(level_token[1:]), "title": title})
    return out


def normalize_key(value: str) -> str:
    return re.sub(r"[\s　]+", "", str(value or "")).lower()


def extract_section_from_attach(value: str) -> str:
    match = re.search(r"(?<!\d)(\d+(?:\.\d+){0,4})(?!\d)", str(value or ""))
    return match.group(1) if match else ""


def infer_section_from_text(*values: str) -> str:
    text = " ".join(str(value or "") for value in values)
    direct = extract_section_from_attach(text)
    if direct:
        return direct
    mapping = [
        ("风资源", "3.3"),
        ("机组选型", "3.4"),
        ("技术承诺", "4"),
        ("自主可控", "1.4"),
        ("关键数据", "1.6"),
        ("评分", "1.1"),
        ("业绩", "1.8"),
        ("公司概况", "1.9"),
        ("技术标准", "2"),
        ("关键部件", "5.8"),
        ("子系统", "5.8"),
        ("环境适应", "5.9"),
        ("塔筒", "5.10"),
        ("质量", "5.11"),
        ("交货", "6.1"),
        ("运输", "5.13"),
        ("安装", "5.14"),
        ("运维", "5.16"),
        ("碳排放", "5.17"),
        ("数字化", "5.18"),
        ("智慧风场", "5.18"),
    ]
    for keyword, section in mapping:
        if keyword in text:
            return section
    return ""


def parse_heading_summary(value: str) -> tuple[int, str]:
    text = str(value or "").strip()
    count = 0
    level_range = "none"
    match = re.search(r"(\d+)", text)
    if match:
        count = int(match.group(1))
    range_match = re.search(r"\((L\d+\s*-\s*L\d+|L\d+)\)", text)
    if range_match:
        level_range = range_match.group(1).replace(" ", "")
    return count, level_range


def parse_material_entries(text: str, card_meta: dict) -> list[dict]:
    """从聚合 Wiki 卡片正文中拆出具体素材条目。

    现在数据库 Wiki 经常是一张“技术标通用卡片”里包含多个 `### 素材名`
    小节。目录生成需要读这些小节，而不是把整张聚合卡片当一个素材。
    """
    entries = []
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        fields = current.get("fields") or {}
        if not any(key in fields for key in ("id", "docx", "attach", "skeleton", "usage", "headings")):
            current = None
            return

        title = str(current.get("title") or "").strip()
        usage = str(fields.get("usage") or "")
        if usage == "directory" and title in {"投标文件-模板", "投标文件模板", "主模板"}:
            current = None
            return
        attach = str(fields.get("attach") or "")
        skeleton = str(fields.get("skeleton") or "")
        section = extract_section_from_attach(attach) or infer_section_from_text(title, skeleton, attach, fields.get("docx", ""))
        heading_count, material_level_range = parse_heading_summary(str(fields.get("headings") or ""))
        scope = str(card_meta.get("scope") or "")
        if fields.get("condition") and scope != "通用":
            scope = "定制"
        identity_scope = str(fields.get("identity_scope") or card_meta.get("identity_scope") or "")
        customer_id = str(fields.get("customer_id") or card_meta.get("customer_id") or "")
        customer_name = str(fields.get("customer_name") or card_meta.get("customer_name") or "")
        customer_aliases = str(fields.get("customer_aliases") or card_meta.get("customer_aliases") or "")
        project_id = str(fields.get("project_id") or card_meta.get("project_id") or "")
        project_code = str(fields.get("project_code") or card_meta.get("project_code") or "")
        entries.append(
            {
                "section": section or str(card_meta.get("skeleton_section") or "未明确"),
                "level": section_to_level(section),
                "display_name": title,
                "source_name": title,
                "scope": scope,
                "category": str(card_meta.get("category") or ""),
                "identity_scope": identity_scope,
                "customer_id": customer_id,
                "customer_name": customer_name,
                "customer_aliases": customer_aliases,
                "project_id": project_id,
                "project_code": project_code,
                "skeleton_level": str(card_meta.get("skeleton_level") or "section"),
                "material_level_range": material_level_range,
                "heading_count": heading_count,
                "internal_headings": [],
                "shift": int(card_meta.get("shift") or 0),
                "attach_mode": str(card_meta.get("attach_mode") or "normal"),
                "condition": str(fields.get("condition") or card_meta.get("condition") or ""),
                "path": f"{card_meta.get('path')}/{title}".strip("/"),
                "material_ref": {
                    "id": str(fields.get("id") or ""),
                    "docx": str(fields.get("docx") or ""),
                    "usage": usage,
                    "attach": attach,
                    "skeleton": skeleton,
                    "fields": str(fields.get("fields") or ""),
                    "identity_scope": identity_scope,
                    "customer_id": customer_id,
                    "customer_name": customer_name,
                    "customer_aliases": customer_aliases,
                    "project_id": project_id,
                    "project_code": project_code,
                },
            }
        )
        current = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        heading = re.match(r"^###\s+(.+?)\s*$", line)
        if heading:
            flush()
            current = {"title": heading.group(1).strip(), "fields": {}}
            continue
        if current is None:
            continue
        bullet = re.match(r"^-\s+\*\*([^*]+)\*\*\s*:\s*(.*)$", line.strip())
        if not bullet:
            continue
        key = normalize_key(bullet.group(1))
        value = bullet.group(2).strip()
        key_map = {
            "id": "id",
            "docx": "docx",
            "usage": "usage",
            "headings": "headings",
            "skeleton": "skeleton",
            "attach": "attach",
            "condition": "condition",
            "fields": "fields",
            "note": "note",
            "identityscope": "identity_scope",
            "identity_scope": "identity_scope",
            "customerid": "customer_id",
            "customer_id": "customer_id",
            "customername": "customer_name",
            "customer_name": "customer_name",
            "customeraliases": "customer_aliases",
            "customer_aliases": "customer_aliases",
            "projectid": "project_id",
            "project_id": "project_id",
            "projectcode": "project_code",
            "project_code": "project_code",
        }
        normalized = key_map.get(key)
        if normalized:
            current["fields"][normalized] = value

    flush()
    return entries


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
        "material_id": fm.get("material_id", ""),
        "identity_scope": fm.get("identity_scope", ""),
        "material_scope": fm.get("material_scope", ""),
        "bid_type": fm.get("bid_type", ""),
        "customer_id": fm.get("customer_id", ""),
        "customer_name": fm.get("customer_name", ""),
        "customer_aliases": fm.get("customer_aliases", ""),
        "project_id": fm.get("project_id", ""),
        "project_code": fm.get("project_code", ""),
        "skeleton_section": fm.get("skeleton_section", "未明确"),
        "skeleton_level": fm.get("skeleton_level", "unknown"),
        "material_level_range": fm.get("material_level_range", "none"),
        "heading_count": fm.get("heading_count", 0),
        "internal_headings": extract_internal_headings(text),
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
    cards = wiki_root / "卡片"
    for p in cards.rglob("*.md"):
        c = lookup(wiki_root, p.stem)
        if not c.get("found"):
            continue
        if c.get("deprecated"):
            continue
        text = p.read_text(encoding="utf-8")
        material_entries = parse_material_entries(text, c)
        if material_entries:
            items.extend(material_entries)
            continue
        section = str(c.get("skeleton_section", ""))
        if section in ("", "未明确"):
            inferred_section = infer_section_from_text(c.get("name", ""), c.get("path", ""), c.get("category", ""))
            if inferred_section:
                section = inferred_section
        items.append({
            "section": section,
            "level": section_to_level(section),
            "display_name": strip_prefix(c["name"]),
            "source_name": c["name"],
            "scope": c.get("scope", ""),
            "category": c.get("category", ""),
            "material_id": c.get("material_id", ""),
            "identity_scope": c.get("identity_scope", ""),
            "material_scope": c.get("material_scope", ""),
            "bid_type": c.get("bid_type", ""),
            "customer_id": c.get("customer_id", ""),
            "customer_name": c.get("customer_name", ""),
            "customer_aliases": c.get("customer_aliases", ""),
            "project_id": c.get("project_id", ""),
            "project_code": c.get("project_code", ""),
            "skeleton_level": c.get("skeleton_level", "unknown"),
            "material_level_range": c.get("material_level_range", "none"),
            "heading_count": c.get("heading_count", 0),
            "internal_headings": c.get("internal_headings", []),
            "shift": c.get("shift", 0),
            "attach_mode": c.get("attach_mode", "normal"),
            "condition": c.get("condition", ""),
            "path": c.get("path", ""),
            "material_ref": {
                "id": "",
                "docx": "",
                "usage": "",
                "attach": "",
                "skeleton": section,
                "fields": "",
                "identity_scope": c.get("identity_scope", ""),
                "customer_id": c.get("customer_id", ""),
                "customer_name": c.get("customer_name", ""),
                "customer_aliases": c.get("customer_aliases", ""),
                "project_id": c.get("project_id", ""),
                "project_code": c.get("project_code", ""),
            },
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
