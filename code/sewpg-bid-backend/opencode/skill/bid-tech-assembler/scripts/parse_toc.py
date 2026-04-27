#!/usr/bin/env python3
"""
解析投标目录 docx，输出 toc.json。

每条目：
  {
    "idx": int,                   # 顺序位置（0-based）
    "level": int,                 # 1-6
    "chapter_no": str,            # "1"/"1.1"/"5.8.1"/"第一章"/"前言"/"附"/""
    "chapter_no_flat": str,       # "1"/"1.1"/"5.8.1"/""（中文章名映射成阿拉伯；前言/附为空）
    "title": str,                 # 纯标题（去章节号、去（新增）/（适配）标签）
    "raw_text": str,              # 原始 Heading 文本（debug 用）
    "tag": "normal"|"新增"|"适配",
    "is_preface": bool,           # 前言段
    "is_appendix": bool,          # "附" 开头，挂父节
  }

跳过第一行文档标题（含"总目录"字样）和附表/附件专属段（本 skill 范围不处理）。

用法：
    python3 parse_toc.py <目录 docx> [--out toc.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

from docx import Document


# ---------- 中文数字 ↔ 阿拉伯 ----------

_CN_NUM = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "百": 100, "千": 1000, "万": 10000,
}


def _cn_to_int(s: str) -> Optional[int]:
    """把中文数字转阿拉伯整数；解析失败返回 None。只处理 1-999。"""
    if not s:
        return None
    if s.isdigit():
        return int(s)
    # 特殊：十/二十/三十几
    if "十" in s:
        left, _, right = s.partition("十")
        l = _CN_NUM.get(left, 1) if left else 1
        r = _CN_NUM.get(right, 0) if right else 0
        return l * 10 + r
    # 单个字
    if len(s) == 1 and s in _CN_NUM:
        return _CN_NUM[s]
    # fallback：逐字累加
    total = 0
    for c in s:
        if c in _CN_NUM:
            total = total * 10 + _CN_NUM[c]
        else:
            return None
    return total


# ---------- Heading 样式判定 ----------

def _heading_level(style_name: str) -> Optional[int]:
    if not style_name:
        return None
    s = style_name.strip()
    m = re.match(r"^Heading\s+(\d+)$", s)
    if m:
        return int(m.group(1))
    m = re.match(r"^标题\s*(\d+)$", s)
    if m:
        return int(m.group(1))
    return None


# ---------- 单条 Heading 文本解析 ----------

_TAG_PATTERN = re.compile(r"[（(](新增|适配)[)）]\s*$")
_PREFACE_PATTERN = re.compile(r"^前言(\s|$)")
_APPENDIX_PATTERN = re.compile(r"^附(\s|$|[:：])")
_CHAPTER_CN_PATTERN = re.compile(r"^第([一二三四五六七八九十百千万零〇\d]+)章\s*")
_NUMBER_PATTERN = re.compile(r"^(\d+(?:\.\d+)*)\s+")


def parse_heading_text(text: str) -> dict:
    """解析单行 Heading 文本。

    返回 {chapter_no, chapter_no_flat, title, tag, is_preface, is_appendix}。
    """
    raw = (text or "").strip()
    tag = "normal"
    m = _TAG_PATTERN.search(raw)
    if m:
        tag = m.group(1)
        raw_notag = _TAG_PATTERN.sub("", raw).strip()
    else:
        raw_notag = raw

    # 前言段
    if _PREFACE_PATTERN.match(raw_notag):
        rest = re.sub(r"^前言\s*", "", raw_notag).strip()
        return {
            "chapter_no": "前言",
            "chapter_no_flat": "",
            "title": rest or "前言",
            "tag": tag,
            "is_preface": True,
            "is_appendix": False,
        }

    # 附 开头（挂父节）
    if _APPENDIX_PATTERN.match(raw_notag):
        rest = re.sub(r"^附\s*[:：]?\s*", "", raw_notag).strip()
        return {
            "chapter_no": "附",
            "chapter_no_flat": "",
            "title": rest,
            "tag": tag,
            "is_preface": False,
            "is_appendix": True,
        }

    # 第X章
    m = _CHAPTER_CN_PATTERN.match(raw_notag)
    if m:
        n_str = m.group(1)
        n_int = _cn_to_int(n_str)
        rest = _CHAPTER_CN_PATTERN.sub("", raw_notag).strip()
        return {
            "chapter_no": f"第{n_str}章",
            "chapter_no_flat": str(n_int) if n_int is not None else "",
            "title": rest,
            "tag": tag,
            "is_preface": False,
            "is_appendix": False,
        }

    # 阿拉伯数字点分 "1.1  xxx"
    m = _NUMBER_PATTERN.match(raw_notag)
    if m:
        num = m.group(1)
        rest = _NUMBER_PATTERN.sub("", raw_notag).strip()
        return {
            "chapter_no": num,
            "chapter_no_flat": num,
            "title": rest,
            "tag": tag,
            "is_preface": False,
            "is_appendix": False,
        }

    # 无编号
    return {
        "chapter_no": "",
        "chapter_no_flat": "",
        "title": raw_notag,
        "tag": tag,
        "is_preface": False,
        "is_appendix": False,
    }


# ---------- 主流程 ----------

def parse_toc_docx(docx_path: Path) -> list[dict]:
    doc = Document(str(docx_path))
    entries: list[dict] = []
    idx = 0
    for para in doc.paragraphs:
        lvl = _heading_level(para.style.name if para.style else "")
        if lvl is None:
            continue
        text = (para.text or "").strip()
        if not text:
            continue
        # 首行文档标题：含"总目录"字样，且 level=1 → 跳过
        if idx == 0 and "总目录" in text and lvl == 1:
            continue
        parsed = parse_heading_text(text)
        entries.append({
            "idx": idx,
            "level": lvl,
            "raw_text": text,
            **parsed,
        })
        idx += 1
    return entries


def _annotation_to_tag(value: str) -> str:
    text = str(value or "").strip()
    if "新增" in text:
        return "新增"
    if "适配" in text:
        return "适配"
    return "normal"


def _json_heading_text(item: dict) -> str:
    number = str(
        item.get("number")
        or item.get("chapter_no")
        or item.get("chapterNo")
        or item.get("section")
        or ""
    ).strip()
    title = str(item.get("title") or item.get("name") or "").strip()
    if number.startswith("附表") and not title:
        return "附表"
    if number and title:
        return f"{number} {title}"
    return title or number


def _entry_from_json_item(item: dict, idx: int) -> dict:
    text = _json_heading_text(item)
    parsed = parse_heading_text(text)
    annotation = str(item.get("annotation") or item.get("tag") or "")
    parsed["tag"] = _annotation_to_tag(annotation) if annotation else parsed["tag"]
    level = item.get("level")
    try:
        level = int(level)
    except (TypeError, ValueError):
        level = max(1, parsed.get("chapter_no_flat", "").count(".") + 1)
    if text == "附表":
        parsed["title"] = "附表"
        parsed["chapter_no"] = "附表"
        parsed["chapter_no_flat"] = ""
    return {
        "idx": idx,
        "level": max(1, min(6, level)),
        "raw_text": text,
        **parsed,
    }


def _flatten_outline_nodes(nodes: list[dict], prefix: str = "", level: int = 1) -> list[dict]:
    entries: list[dict] = []
    for index, node in enumerate(nodes, start=1):
        number = f"{prefix}.{index}" if prefix else str(index)
        entries.append(
            {
                "order": len(entries),
                "level": level,
                "number": number,
                "title": str(node.get("title") or node.get("name") or "").strip(),
                "annotation": str(node.get("annotation") or node.get("tag") or ""),
            }
        )
        children = node.get("children") or []
        if isinstance(children, list):
            child_entries = _flatten_outline_nodes(children, number, level + 1)
            entries.extend(child_entries)
    return entries


def parse_toc_json(json_path: Path) -> list[dict]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        raw_items = data
    elif isinstance(data, dict) and isinstance(data.get("items"), list):
        raw_items = data["items"]
    elif isinstance(data, dict) and isinstance(data.get("nodes"), list):
        raw_items = _flatten_outline_nodes(data["nodes"])
    else:
        raise RuntimeError("目录 JSON 必须包含 items[] 或 nodes[]。")

    entries: list[dict] = []
    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        entry = _entry_from_json_item(item, idx)
        if not entry["raw_text"]:
            continue
        entries.append(entry)
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("toc", type=Path, help="目录 docx 或当前 S2 目录 JSON 路径")
    ap.add_argument("--out", type=Path, default=None, help="输出 JSON（默认 stdout）")
    args = ap.parse_args()

    if not args.toc.exists():
        print(f"[ERR] not found: {args.toc}", file=sys.stderr)
        sys.exit(1)

    if args.toc.suffix.lower() == ".json":
        entries = parse_toc_json(args.toc)
    else:
        entries = parse_toc_docx(args.toc)
    out_text = json.dumps(entries, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(out_text, encoding="utf-8")
        print(f"[OK] {len(entries)} entries → {args.out}", file=sys.stderr)
    else:
        print(out_text)


if __name__ == "__main__":
    main()
