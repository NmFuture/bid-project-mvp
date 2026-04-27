#!/usr/bin/env python3
"""extract_template.py — 抽取投标正文模板的 H1/H2 章节框架

用 python-docx 直接读 Heading 1/2 段落（比 officecli 稳定）。

用法：
    python3 extract_template.py <投标正文模板.docx> [--max-level 2]

输出 JSON：
    {"chapters": [
       {"num": "1", "title": "标前概述", "heading_level": 1,
        "h2s": [{"num": "1.1", "title": "技术评分标准索引表"}, ...]
       }, ...
    ]}
"""
import argparse
import json
import re
import sys
from pathlib import Path

try:
    from docx import Document
except ImportError:
    print("ERROR: python-docx 未安装。pip install python-docx", file=sys.stderr)
    sys.exit(1)


CN_NUM_MAP = {"一":"1","二":"2","三":"3","四":"4","五":"5","六":"6","七":"7","八":"8","九":"9","十":"10"}
MAX_TITLE_CHARS = 64
MAX_TOP_LEVEL_NUM = 12
TOC_ORIGIN = "toc"
HEADING_ORIGIN = "heading"
INFERRED_ORIGIN = "inferred"


def parse_number(text: str):
    """从段落文本抽 章节号 和 标题。
    识别：第一章 / 1 / 1.1 / 一、/ 1. / 一. 等前缀。
    返回 (num, title)；识别不出返回 (None, text)。"""
    t = text.strip()
    # 第一章 / 第二章 ...
    m = re.match(r"^第([一二三四五六七八九十百\d]+)章[\s　]*(.*)$", t)
    if m:
        raw_num = m.group(1)
        return raw_num if raw_num.isdigit() else CN_NUM_MAP.get(raw_num, raw_num), m.group(2).strip()
    # 1.2.3  或 1.2  或 1
    m = re.match(r"^(\d+(?:\.\d+)*)(?:[\s　]+|[.．、）)])(.+)$", t)
    if m:
        return m.group(1), clean_title(m.group(2))
    # 附表1 / 附表 A ...
    m = re.match(r"^(附表\s*[A-Za-z一二三四五六七八九十百\d]+)[\s　]*(.*)$", t)
    if m:
        return re.sub(r"\s+", "", m.group(1)), clean_title(m.group(2))
    # 一、xxx
    m = re.match(r"^([一二三四五六七八九十]+)[、.，]\s*(.*)$", t)
    if m:
        return CN_NUM_MAP.get(m.group(1), m.group(1)), m.group(2).strip()
    return None, t


def clean_title(text: str) -> str:
    """Remove TOC page-number tails and compact whitespace in extracted headings."""
    title = re.sub(r"\s+", " ", str(text or "")).strip()
    title = re.sub(r"[\t ]+\d{1,4}$", "", title).strip()
    return title


def top_level_number(num: str | None) -> int | None:
    if not num:
        return None
    first = str(num).split(".", 1)[0]
    try:
        return int(first)
    except ValueError:
        return None


def title_key(title: str) -> str:
    return re.sub(r"[\s　,，、.。:：()（）\[\]【】\-—_]+", "", str(title or "")).lower()


def page_number(raw_text: str) -> str:
    match = re.search(r"[\t ]+(\d{1,4})$", str(raw_text or "").strip())
    return match.group(1) if match else ""


def plausible_heading(raw_text: str, num: str | None, title: str, level: int) -> bool:
    text = str(raw_text or "").strip()
    clean = clean_title(title)
    if not clean:
        return False
    if len(clean) > MAX_TITLE_CHARS:
        return False
    if re.match(r"^\d{4}年", text):
        return False
    if clean.startswith("#"):
        return False
    if clean.endswith(("。", "；", ";")):
        return False
    if len(clean) > 28 and any(mark in clean for mark in ("，", "；", "。")):
        return False
    if level == 1:
        top = top_level_number(num)
        if top is not None and top > MAX_TOP_LEVEL_NUM:
            return False
    return True


def toc_level(style_name: str) -> int:
    """Word TOC 样式：toc 1 / toc 2 / 目录 1。"""
    if not style_name:
        return 0
    s = style_name.lower().strip()
    m = re.match(r"^toc\s*(\d+)$", s)
    if m:
        return int(m.group(1))
    m = re.match(r"^目录\s*(\d+)$", style_name.strip())
    if m:
        return int(m.group(1))
    return 0


def heading_level(style_name: str) -> int:
    """'Heading 1' / 'heading 2' / '标题 1' → 层级；非 heading 返回 0"""
    if not style_name:
        return 0
    s = style_name.lower().replace(" ", "")
    m = re.match(r"^(?:heading|标题)(\d+)$", s)
    if m:
        return int(m.group(1))
    return 0


def candidate_level(style_name: str, text: str, max_level: int) -> tuple[int, str]:
    toc = toc_level(style_name)
    if toc:
        return toc, TOC_ORIGIN
    heading = heading_level(style_name)
    if heading:
        return heading, HEADING_ORIGIN
    inferred = inferred_heading_level(text, max_level)
    if inferred:
        return inferred, INFERRED_ORIGIN
    return 0, ""


def inferred_heading_level(text: str, max_level: int) -> int:
    """Fallback for templates whose visual headings are plain Normal paragraphs."""
    if not text or len(text) > 100:
        return 0
    num, title = parse_number(text)
    if not num or not title:
        return 0
    if "." not in str(num):
        return 1 if max_level >= 1 else 0
    level = str(num).count(".") + 1
    return level if 1 <= level <= max_level else 0


def collect_candidates(doc: Document, max_level: int) -> list[dict]:
    candidates = []
    for index, p in enumerate(doc.paragraphs):
        text = (p.text or "").strip()
        if not text:
            continue
        style_name = p.style.name if p.style else ""
        lvl, origin = candidate_level(style_name, text, max_level)
        if lvl < 1 or lvl > max_level:
            continue
        num, title = parse_number(text)
        title = clean_title(title)
        if origin == TOC_ORIGIN and lvl == 1 and not num:
            # TOC 里常有“投标说明函 2”这类无编号前置项，避免挤占第 1 章。
            continue
        if not plausible_heading(text, num, title, lvl):
            continue
        candidates.append(
            {
                "index": index,
                "level": lvl,
                "origin": origin,
                "num": num,
                "title": title,
                "raw_text": text,
                "style": style_name,
                "page": page_number(text),
            }
        )
    return candidates


def extract(docx_path: Path, max_level: int = 2) -> dict:
    doc = Document(str(docx_path))
    candidates = collect_candidates(doc, max_level)
    toc_h1_count = sum(
        1
        for item in candidates
        if item["origin"] == TOC_ORIGIN and item["level"] == 1 and item.get("num")
    )
    if toc_h1_count >= 2:
        # 真实模板常同时含 TOC 页和正文 Heading。TOC 是目录生成的主骨架，
        # 一旦可用，就只取 TOC 项，避免正文标题重复进入第 7/8/9 章。
        candidates = [item for item in candidates if item["origin"] == TOC_ORIGIN]

    chapters = []
    current_chapter = None
    seen_chapter_titles: set[str] = set()

    for candidate in candidates:
        lvl = candidate["level"]
        num = candidate["num"]
        title = candidate["title"]
        text = candidate["raw_text"]

        if lvl == 1:
            # H1 无编号 → 按章出现顺序赋 1/2/3...
            if not num:
                num = str(len(chapters) + 1)
            top = top_level_number(num)
            if top is not None and top > MAX_TOP_LEVEL_NUM:
                continue
            key = title_key(title)
            if key and key in seen_chapter_titles:
                continue
            if any(chapter.get("num") == num for chapter in chapters):
                continue
            seen_chapter_titles.add(key)
            current_chapter = {
                "num": num,
                "title": title or text,
                "raw_text": text,
                "source_kind": candidate["origin"],
                "style": candidate["style"],
                "page": candidate["page"],
                "h2s": [],
            }
            chapters.append(current_chapter)
        elif lvl == 2 and current_chapter is not None:
            # H2 无编号 → 按"父章.顺序"赋
            if not num:
                num = f"{current_chapter['num']}.{len(current_chapter['h2s']) + 1}"
            elif "." in str(num) and str(num).split(".", 1)[0] != str(current_chapter["num"]):
                continue
            current_chapter["h2s"].append({
                "num": num,
                "title": title or text,
                "raw_text": text,
                "source_kind": candidate["origin"],
                "style": candidate["style"],
                "page": candidate["page"],
            })

    return {"chapters": chapters, "source": str(docx_path)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx", help="投标正文模板 docx 路径")
    ap.add_argument("--max-level", type=int, default=2, help="抽到第几级（默认 2）")
    args = ap.parse_args()
    p = Path(args.docx).expanduser().resolve()
    if not p.exists():
        print(f"ERROR: {p} 不存在", file=sys.stderr)
        sys.exit(1)
    result = extract(p, args.max_level)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
