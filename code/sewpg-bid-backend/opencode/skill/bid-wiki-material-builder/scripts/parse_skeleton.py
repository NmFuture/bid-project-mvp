#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解析 skeleton.md → 得到每份素材的 merge 信息
     merge 信息 = (骨架章节号, 骨架 L, 素材 L 范围, Heading 数, shift, 备注, Heading 树片段)

然后把信息注入每张 wiki/卡片/**/*.md：
1. frontmatter 追加字段：skeleton_section / skeleton_level / material_level_range / heading_count / shift
2. 正文末尾追加 "## Merge 信息" 小节（含 Heading 树片段 + 升降级说明）

幂等：再次运行会覆盖已注入的"## Merge 信息"节，不重复追加。
"""
from __future__ import annotations
from pathlib import Path
import re
import sys

WIKI = Path(__file__).resolve().parent.parent  # wiki/scripts/ → wiki/
SKELETON = WIKI / "skeleton.md"
CARD_ROOT = WIKI / "卡片"
ROOT = WIKI.parent  # 素材库/


# ------- parse skeleton.md -------

SECTION_HEADING_RE = re.compile(r"^(#{2,4})\s+(.+?)\s*$")
MERGE_MAT_RE = re.compile(r"^\s*-\s*\*\*merge 素材\*\*[:：]\s*`([^`]+)`\s*$")
LEVEL_LINE_RE = re.compile(
    r"素材层级[:：]?\s*(L\d)[–\-\u2013]+(L\d)[,，]?\s*共\s*(\d+)\s*条"
)
SHIFT_RE = re.compile(r"整体\s*([+\-\u2212]?\d+)\s*(升级|降级)")
BARE_NOHEAD_RE = re.compile(r"无\s*Heading[,，]?\s*整段")


def parse_skeleton():
    """
    返回 list[dict]：每份素材一条
    dict 字段：section_no, section_title, skeleton_level, path_short,
              material_start, material_end, heading_count, shift, note,
              heading_tree (多行字符串，保留缩进), is_no_heading (bool)
    """
    lines = SKELETON.read_text(encoding="utf-8").splitlines()
    entries = []

    # 先建一个 "行号 -> 上下文" 辅助结构
    # 迭代过程中跟踪当前的章节号/标题/骨架L
    cur_section_no = None
    cur_section_title = None
    cur_skeleton_level = None  # L1/L2/L3
    cur_note = None  # 从"备注"行抓
    i = 0
    n = len(lines)

    def clean_section(raw: str) -> tuple[str | None, str]:
        """## 1  标前概述 -> ("1", "标前概述")；### 1.1  技术评分标准索引表 -> ("1.1", "技术评分标准索引表")"""
        # 形如 "1\u3000标前概述" 或 "5.8.1\u3000叶片专题"
        m = re.match(r"^\s*([\d\.]+)\s*[\u3000\s]+\s*(.+?)\s*$", raw)
        if m:
            return m.group(1).rstrip("."), m.group(2).strip()
        return None, raw.strip()

    while i < n:
        line = lines[i]
        # 章节标题
        mh = SECTION_HEADING_RE.match(line)
        if mh:
            # 切新章节，重置 note
            sec_no, sec_title = clean_section(mh.group(2))
            if sec_no:
                cur_section_no = sec_no
                cur_section_title = sec_title
                cur_skeleton_level = None
                cur_note = None
            i += 1
            continue

        # 骨架生成层级
        m = re.match(r"^\s*-\s*\*\*骨架生成层级\*\*[:：]\s*(L\d)\s*$", line)
        if m:
            cur_skeleton_level = m.group(1)
            i += 1
            continue

        # 备注
        m = re.match(r"^\s*-\s*\*\*备注\*\*[:：]\s*(.+?)\s*$", line)
        if m:
            cur_note = m.group(1).strip()
            i += 1
            continue

        # merge 素材行
        m = MERGE_MAT_RE.match(line)
        if m:
            path_short = m.group(1).strip()
            # 接下来查后续行，直到下一个 merge 素材、或下一个 ### 标题、或 `---` 分隔
            block_start = i + 1
            block_end = i + 1
            while block_end < n:
                l2 = lines[block_end]
                if MERGE_MAT_RE.match(l2):
                    break
                if SECTION_HEADING_RE.match(l2):
                    break
                if l2.strip() == "---":
                    break
                block_end += 1

            block = "\n".join(lines[block_start:block_end])

            # 抽取层级范围/count
            material_start = material_end = heading_count = None
            mlv = LEVEL_LINE_RE.search(block)
            if mlv:
                material_start = mlv.group(1)
                material_end = mlv.group(2)
                heading_count = int(mlv.group(3))
            is_no_heading = bool(BARE_NOHEAD_RE.search(block))

            # 抽取 shift
            shift = 0
            ms = SHIFT_RE.search(block)
            if ms:
                num = ms.group(1).replace("\u2212", "-")
                try:
                    val = int(num)
                except ValueError:
                    val = 0
                if ms.group(2) == "升级":
                    shift = -abs(val)
                else:  # 降级
                    shift = abs(val)

            # 抽取 heading 树（从 "贴入后自动展开成以下子节：" 下面开始，以空行或下一个条目结束）
            tree_lines = []
            tree_started = False
            for l2 in lines[block_start:block_end]:
                if "贴入后自动展开" in l2:
                    tree_started = True
                    continue
                if not tree_started:
                    continue
                # 树内容通常为 4 空格开头的缩进行
                if l2.strip() == "":
                    # 空行跳过，可能是分隔
                    if tree_lines and tree_lines[-1].strip() != "":
                        tree_lines.append("")
                    continue
                if l2.startswith("    ") or l2.startswith("\t"):
                    tree_lines.append(l2.rstrip())
                else:
                    # 遇到非缩进就停止
                    break
            # 裁尾空行
            while tree_lines and tree_lines[-1].strip() == "":
                tree_lines.pop()
            heading_tree = "\n".join(tree_lines)

            entries.append({
                "section_no": cur_section_no,
                "section_title": cur_section_title,
                "skeleton_level": cur_skeleton_level,
                "path_short": path_short,
                "material_start": material_start,
                "material_end": material_end,
                "heading_count": heading_count,
                "shift": shift,
                "note": cur_note,
                "heading_tree": heading_tree,
                "is_no_heading": is_no_heading,
            })

            i = block_end
            continue

        i += 1

    return entries


def expand_path(path_short: str) -> str:
    """把 skeleton 里的 '通/...' / '定/...' 还原为 '投标资料库-通用/...' / '投标资料库-定制/...'"""
    if path_short.startswith("通/"):
        return "投标资料库-通用/" + path_short[2:]
    if path_short.startswith("定/"):
        return "投标资料库-定制/" + path_short[2:]
    return path_short


def find_card(full_path: str) -> Path | None:
    """根据素材路径找到对应卡片 md"""
    stem = Path(full_path).stem
    hits = list(CARD_ROOT.rglob(f"{stem}.md"))
    if not hits:
        return None
    if len(hits) > 1:
        # 多命中时优先匹配 scope (通用 vs 定制)
        is_custom = full_path.startswith("投标资料库-定制/")
        for h in hits:
            if is_custom and "/定制/" in str(h):
                return h
            if not is_custom and "/通用/" in str(h):
                return h
    return hits[0]


# ------- inject into card -------

FRONT_FIELD_KEYS = (
    "skeleton_section",
    "skeleton_level",
    "material_level_range",
    "heading_count",
    "shift",
)

MERGE_SECTION_MARK_START = "<!-- MERGE_INFO_START -->"
MERGE_SECTION_MARK_END = "<!-- MERGE_INFO_END -->"


def render_merge_section(e: dict) -> str:
    """生成 '## Merge 信息' 节"""
    parts = [MERGE_SECTION_MARK_START, "", "## Merge 信息"]
    parts.append(f"- 投标骨架章节号：**{e['section_no']}** {e['section_title']}")
    parts.append(f"- 骨架生成层级：**{e['skeleton_level'] or '未明确'}**")
    if e["material_start"] and e["material_end"]:
        parts.append(
            f"- 素材内部层级：{e['material_start']}–{e['material_end']}（共 {e['heading_count']} 条 Heading）"
        )
    elif e["is_no_heading"]:
        parts.append("- 素材内部层级：**无 Heading，整段作为正文/附录贴入**")
    shift = e.get("shift", 0)
    if shift == 0:
        parts.append("- 升降级：无（素材起始层级与骨架层级一致，直接贴入）")
    elif shift > 0:
        parts.append(f"- 升降级：**整体 +{shift} 降级**（素材 L 值整体向下推 {shift} 层后贴入）")
    else:
        parts.append(f"- 升降级：**整体 {shift} 升级**（素材 L 值整体向上提 {abs(shift)} 层后贴入）")
    if e.get("note"):
        parts.append(f"- 备注：{e['note']}")
    if e["heading_tree"]:
        parts.append("")
        parts.append("### 素材内部 Heading 树")
        parts.append("```")
        parts.append(e["heading_tree"])
        parts.append("```")
    parts.append("")
    parts.append(MERGE_SECTION_MARK_END)
    return "\n".join(parts)


def update_front_matter(card_text: str, e: dict) -> str:
    """在 frontmatter 里替换/追加 merge 字段"""
    m = re.search(r"^---\s*\n(.*?)\n---\s*\n", card_text, re.DOTALL)
    if not m:
        return card_text
    header_body = m.group(1)
    keep_lines = []
    for line in header_body.splitlines():
        k = line.split(":", 1)[0].strip()
        if k in FRONT_FIELD_KEYS:
            continue  # 删旧值，稍后追加新值
        keep_lines.append(line)
    # 追加新字段
    keep_lines.append(f"skeleton_section: \"{e['section_no']}\"")
    keep_lines.append(f"skeleton_level: {e['skeleton_level'] or 'unknown'}")
    if e["material_start"]:
        keep_lines.append(f"material_level_range: {e['material_start']}-{e['material_end']}")
    else:
        keep_lines.append("material_level_range: none")
    keep_lines.append(f"heading_count: {e['heading_count'] if e['heading_count'] is not None else 0}")
    keep_lines.append(f"shift: {e.get('shift', 0)}")
    new_header = "\n".join(keep_lines)
    return card_text[:m.start()] + "---\n" + new_header + "\n---\n" + card_text[m.end():]


def inject_merge_section(card_text: str, merge_block: str) -> str:
    """在正文末尾追加/替换 '## Merge 信息' 节"""
    # 定位已有的标记块
    pat = re.compile(
        re.escape(MERGE_SECTION_MARK_START) + r".*?" + re.escape(MERGE_SECTION_MARK_END),
        re.DOTALL,
    )
    if pat.search(card_text):
        return pat.sub(merge_block, card_text)
    # 否则在文件末尾追加（保证单换行结尾 → 追加双换行 + 块）
    if not card_text.endswith("\n"):
        card_text += "\n"
    return card_text + "\n" + merge_block + "\n"


def main():
    entries = parse_skeleton()
    matched, missing = [], []
    for e in entries:
        full_path = expand_path(e["path_short"])
        card = find_card(full_path)
        if not card:
            missing.append((e["path_short"], e["section_no"]))
            continue
        txt = card.read_text(encoding="utf-8")
        txt = update_front_matter(txt, e)
        txt = inject_merge_section(txt, render_merge_section(e))
        card.write_text(txt, encoding="utf-8")
        matched.append((card.relative_to(WIKI).as_posix(), e["section_no"]))

    print(f"处理完成。解析 {len(entries)} 条 merge 素材，成功注入 {len(matched)} 张卡片。")
    if missing:
        print(f"\n未匹配到卡片 {len(missing)} 条：")
        for p, s in missing:
            print(f"  § {s}  {p}")
    # 打印没被 skeleton 覆盖的卡片（如 技术标-技术标准、基础工程量 等可能不在 skeleton 里）
    all_cards = {p.relative_to(WIKI).as_posix() for p in CARD_ROOT.rglob("*.md")}
    covered = {m[0] for m in matched}
    untouched = sorted(all_cards - covered)
    if untouched:
        print(f"\n未被 skeleton.md 覆盖的卡片 {len(untouched)} 张（骨架未明确位置或附表类）：")
        for c in untouched:
            print(f"  - {c}")


if __name__ == "__main__":
    sys.exit(main() or 0)
