#!/usr/bin/env python3
"""extract_attach.py — 抽投标附表模板 docx 的 A–I 分类与子表

用 python-docx 读 Heading 段落，识别 "附表 X"、"X.Y" 等编号。

用法：
    python3 extract_attach.py <投标文件-附表.docx>

输出 JSON：
    {"classes": [
       {"letter": "A", "title": "投标机型总体方案",
        "subs": [{"num": "A.1", "title": "投标机型方案概述"}, ...]
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


def heading_level(style_name: str) -> int:
    if not style_name:
        return 0
    s = style_name.lower().replace(" ", "")
    m = re.match(r"^(?:heading|标题)(\d+)$", s)
    return int(m.group(1)) if m else 0


def parse_attach(text: str):
    """识别附表编号。附表模板常用 Normal 样式而非 Heading，所以不依赖 style。
    识别：
    - '技术附表 A 标题' / '附表 A 标题'  → class
    - '附表A.1 标题' / '附表 A.1 标题'    → sub
    - '附表A.1.1 标题'                    → subsub
    """
    t = text.strip()
    # 去掉可能的"1. " / "（1）"序号前缀
    t = re.sub(r"^(?:\d+[\.、]|\(\d+\)|（\d+）)\s*", "", t)
    # 大类：[技术]附表 A xxx（后面不能紧跟 "."）
    m = re.match(r"^(?:技术)?附表[\s　]*([A-Z])(?![A-Z.\d])[\s　:：]*(.*)$", t)
    if m:
        return ("class", m.group(1), m.group(2).strip())
    # 子表：附表A.1 / 附表 A.1.1
    m = re.match(r"^(?:技术)?附表[\s　]*([A-Z](?:\.\d+)+)[\s　.、:：]*(.*)$", t)
    if m:
        return ("sub", m.group(1), m.group(2).strip())
    # 裸 A.1
    m = re.match(r"^([A-Z](?:\.\d+)+)[\s　.、:：]+(.*)$", t)
    if m:
        return ("sub", m.group(1), m.group(2).strip())
    return None


def extract(docx_path: Path) -> dict:
    doc = Document(str(docx_path))
    classes = []
    class_index = {}

    for p in doc.paragraphs:
        text = (p.text or "").strip()
        if not text:
            continue
        parsed = parse_attach(text)
        if not parsed:
            continue
        kind, num, title = parsed
        if kind == "class":
            if num not in class_index:
                c = {"letter": num, "title": title or "", "subs": []}
                classes.append(c)
                class_index[num] = c
            else:
                if not class_index[num]["title"] and title:
                    class_index[num]["title"] = title
        elif kind == "sub":
            letter = num.split(".")[0]
            if letter not in class_index:
                c = {"letter": letter, "title": "", "subs": []}
                classes.append(c)
                class_index[letter] = c
            if not any(s["num"] == num for s in class_index[letter]["subs"]):
                class_index[letter]["subs"].append({"num": num, "title": title})

    classes.sort(key=lambda c: c["letter"])
    for c in classes:
        c["subs"].sort(key=lambda s: tuple(int(x) for x in s["num"].split(".")[1:]))

    return {"classes": classes, "source": str(docx_path)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx")
    args = ap.parse_args()
    p = Path(args.docx).expanduser().resolve()
    if not p.exists():
        print(f"ERROR: {p} 不存在", file=sys.stderr)
        sys.exit(1)
    result = extract(p)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
