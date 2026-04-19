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


def parse_number(text: str):
    """从段落文本抽 章节号 和 标题。
    识别：第一章 / 1 / 1.1 / 一、/ 1. / 一. 等前缀。
    返回 (num, title)；识别不出返回 (None, text)。"""
    t = text.strip()
    # 第一章 / 第二章 ...
    m = re.match(r"^第([一二三四五六七八九十百]+)章[\s　]*(.*)$", t)
    if m:
        return CN_NUM_MAP.get(m.group(1), m.group(1)), m.group(2).strip()
    # 1.2.3  或 1.2  或 1
    m = re.match(r"^(\d+(?:\.\d+)*)[\s　.、）)]*(.*)$", t)
    if m:
        return m.group(1), m.group(2).strip()
    # 一、xxx
    m = re.match(r"^([一二三四五六七八九十]+)[、.，]\s*(.*)$", t)
    if m:
        return CN_NUM_MAP.get(m.group(1), m.group(1)), m.group(2).strip()
    return None, t


def heading_level(style_name: str) -> int:
    """'Heading 1' / 'heading 2' / '标题 1' → 层级；非 heading 返回 0"""
    if not style_name:
        return 0
    s = style_name.lower().replace(" ", "")
    m = re.match(r"^(?:heading|标题)(\d+)$", s)
    if m:
        return int(m.group(1))
    return 0


def extract(docx_path: Path, max_level: int = 2) -> dict:
    doc = Document(str(docx_path))
    chapters = []
    current_chapter = None

    for p in doc.paragraphs:
        lvl = heading_level(p.style.name)
        if lvl < 1 or lvl > max_level:
            continue
        text = (p.text or "").strip()
        if not text:
            continue
        num, title = parse_number(text)

        if lvl == 1:
            # H1 无编号 → 按章出现顺序赋 1/2/3...
            if not num:
                num = str(len(chapters) + 1)
            current_chapter = {
                "num": num,
                "title": title or text,
                "raw_text": text,
                "h2s": [],
            }
            chapters.append(current_chapter)
        elif lvl == 2 and current_chapter is not None:
            # H2 无编号 → 按"父章.顺序"赋
            if not num:
                num = f"{current_chapter['num']}.{len(current_chapter['h2s']) + 1}"
            current_chapter["h2s"].append({
                "num": num,
                "title": title or text,
                "raw_text": text,
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
