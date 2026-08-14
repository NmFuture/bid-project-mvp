#!/usr/bin/env python3
"""
素材 docx 预处理（方案 B）：对单份素材做

1. 归一化 Heading 样式名（标题 N → Heading N）
2. 剥掉所有段落的 w:numPr（破多级列表绑定，方案 B 必须）
3. 剥 Heading 文本原编号前缀（"1.1 xxx" → "xxx"）
4. 洗正文段落手写编号（"7.10 xxx中文" → "xxx中文"；有就洗，没有就不洗）
5. 去 (新增)/(适配)/(如有) 标签
6. 字段占位符替换 [FIELD] → project_params 值

**不做**编号前缀注入 — 那是 merger 的职责（需要父章节号）

输入输出都是 docx 文件路径，不改原文件。

用法：
    python3 preprocess.py <in.docx> <out.docx> [--params params.json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

from docx import Document

from .numbering_fixer import (
    strip_handwritten_numbering_in_body,
    strip_numPr_from_body,
    _replace_paragraph_text_preserve_format,
)
from .docx_style_pruner import prune_unused_styles


def _normalize_headings_by_outline_level(doc) -> int:
    """共性通用：凡 outlineLvl ∈ [0,5] 的段落 → 强制 style = Heading {lvl+1}。
    覆盖所有 WPS / Word 自定义 heading style（章标题、附件标题1、二级标题、专题标题等）。
    """
    from docx.oxml.ns import qn

    # 建 {styleId: outlineLvl(0-based)} map
    style_outline_map = {}
    styles_el = doc.part.styles._element
    for s in styles_el.findall(qn("w:style")):
        sid = s.get(qn("w:styleId"))
        if not sid:
            continue
        pPr = s.find(qn("w:pPr"))
        if pPr is None:
            continue
        ol = pPr.find(qn("w:outlineLvl"))
        if ol is None:
            continue
        try:
            style_outline_map[sid] = int(ol.get(qn("w:val")))
        except (ValueError, TypeError):
            pass

    count = 0
    for para in doc.paragraphs:
        pPr = para._p.find(qn("w:pPr"))
        if pPr is None:
            continue
        direct_ol = pPr.find(qn("w:outlineLvl"))
        effective_lvl = None
        if direct_ol is not None:
            try:
                effective_lvl = int(direct_ol.get(qn("w:val")))
            except (ValueError, TypeError):
                pass
        if effective_lvl is None:
            pStyle = pPr.find(qn("w:pStyle"))
            if pStyle is not None:
                val = pStyle.get(qn("w:val")) or ""
                if val in style_outline_map:
                    effective_lvl = style_outline_map[val]
        if effective_lvl is None or effective_lvl < 0 or effective_lvl > 5:
            continue
        target_style_name = f"Heading {effective_lvl + 1}"
        cur_name = para.style.name if para.style else ""
        if cur_name == target_style_name:
            continue
        try:
            para.style = doc.styles[target_style_name]
            count += 1
        except KeyError:
            pass
    return count


# ---------- 占位符替换 ----------

# project_params 键 → docx 里出现的占位符形式
_PLACEHOLDER_KEY_MAP = {
    "project_name": ["[PROJECT_NAME]", "[项目名称]"],
    "project_short": ["[PROJECT_SHORT]", "[项目简称]"],
    "client_name": ["[CLIENT_NAME]", "[业主]", "[业主名称]"],
    "tender_no": ["[TENDER_NO]", "[招标编号]"],
    "turbine_model": ["[MODEL_NO]", "[机型号]"],
    "turbine_platform": ["[TURBINE_PLATFORM]", "[机型平台]"],
    "rated_power_kw": ["[RATED_POWER]", "[额定功率]"],
    "rated_speed": ["[RATED_SPEED]", "[额定转速]"],
    "rotor_diameter_m": ["[ROTOR_DIAMETER]", "[风轮直径]"],
    "turbine_layout": ["[TURBINE_LAYOUT]", "[风机布局]"],
    "hub_height": ["[HUB_HEIGHT]", "[轮毂高度]"],
    "wind_class": ["[WIND_CLASS]", "[风区等级]"],
    "site_location": ["[SITE_LOCATION]", "[场址位置]"],
    "site_altitude": ["[SITE_ALTITUDE]", "[场址海拔]"],
    "delivery_date": ["[DELIVERY_DATE]", "[交货期]"],
    "warranty_years": ["[WARRANTY_YEARS]", "[质保年限]"],
    "cooling_type": ["[COOLING_TYPE]", "[冷却方式]"],
    "bid_date": ["[BID_DATE]", "[投标日期]"],
    "bid_date_cn": ["[BID_DATE_CN]", "[投标日期中文]"],
    "land_area": ["[LAND_AREA]", "[地块]"],
    "purchase_object": ["[PURCHASE_OBJECT]", "[采购对象]"],
}


def _iter_text_containers(doc):
    for para in doc.paragraphs:
        yield para
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    yield para


def replace_placeholders(doc, params: dict) -> int:
    if not params:
        return 0
    mapping: dict[str, str] = {}
    for key, aliases in _PLACEHOLDER_KEY_MAP.items():
        val = params.get(key)
        if val is None or val == "":
            continue
        val_str = str(val)
        for ph in aliases:
            mapping[ph] = val_str
    if not mapping:
        return 0
    count = 0
    for para in _iter_text_containers(doc):
        if not para.runs:
            continue
        full = para.text
        if not any(ph in full for ph in mapping):
            continue
        new_full = full
        for ph, val in mapping.items():
            if ph in new_full:
                new_full = new_full.replace(ph, val)
        if new_full == full:
            continue
        _replace_paragraph_text_preserve_format(para, new_full)
        count += 1
    return count


# ---------- 断链图形引用清理 ----------

_VML_NS = "urn:schemas-microsoft-com:vml"
_OFFICE_NS = "urn:schemas-microsoft-com:office:office"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_SVG_NS = "http://schemas.microsoft.com/office/drawing/2016/SVG/main"
_DIAGRAM_NS = "http://schemas.openxmlformats.org/drawingml/2006/diagram"


def _drop(element) -> bool:
    parent = element.getparent()
    if parent is None:
        return False
    parent.remove(element)
    return True


def sanitize_dangling_media_refs(doc) -> dict[str, int]:
    """摘掉指向不存在关系的图形引用。

    素材经 WPS 或 doc→docx 转换后常留下只有 o:title、连 r:id 都没有的空 v:imagedata。
    docxcompose 的 add_shapes 取 r:id 时不判空，直接拿 rels[None] 取件，会让整份素材
    以 KeyError: None 合并失败（实测每轮固定丢 2 份素材）。这类元素不指向任何图片，
    摘掉不损失内容；父级 v:shape 保留，里面的文本框和文字原样保留。

    带 o:relid 的老式写法先补成 r:id 再保留，能救回真正有图的那部分。
    """
    rels = doc.part.rels
    stats = {"vml_repaired": 0, "vml_dropped": 0, "blip_dropped": 0, "diagram_dropped": 0}

    for imagedata in list(doc.element.iter(f"{{{_VML_NS}}}imagedata")):
        rid = imagedata.get(f"{{{_REL_NS}}}id")
        if rid is not None and rid in rels:
            continue
        legacy = imagedata.get(f"{{{_OFFICE_NS}}}relid")
        if rid is None and legacy and legacy in rels:
            imagedata.set(f"{{{_REL_NS}}}id", legacy)
            stats["vml_repaired"] += 1
            continue
        if _drop(imagedata):
            stats["vml_dropped"] += 1

    for tag in (f"{{{_DRAWING_NS}}}blip", f"{{{_SVG_NS}}}svgBlip"):
        for blip in list(doc.element.iter(tag)):
            for attr in ("embed", "link"):
                key = f"{{{_REL_NS}}}{attr}"
                rid = blip.get(key)
                if rid is not None and rid not in rels:
                    del blip.attrib[key]
                    stats["blip_dropped"] += 1

    for rel_ids in list(doc.element.iter(f"{{{_DIAGRAM_NS}}}relIds")):
        # 四个部件缺一不可：docxcompose 会逐个取件，缺任何一个都按 rels[None] 崩掉。
        if all(rel_ids.get(f"{{{_REL_NS}}}{item}") in rels for item in ("dm", "lo", "qs", "cs")):
            continue
        if _drop(rel_ids):
            stats["diagram_dropped"] += 1

    return stats


# ---------- 清除 (新增)/(适配)/(如有) 标签 ----------

_TAG_STRIP_PATTERN = re.compile(r"[（(](新增|适配|如有|可选|待定)[)）]")


def strip_tag_marks(doc) -> int:
    count = 0
    for para in _iter_text_containers(doc):
        if not para.runs:
            continue
        full = para.text
        if not _TAG_STRIP_PATTERN.search(full):
            continue
        new_full = _TAG_STRIP_PATTERN.sub("", full)
        if new_full == full:
            continue
        _replace_paragraph_text_preserve_format(para, new_full)
        count += 1
    return count


# ---------- Main ----------

def preprocess_doc(doc, params: Optional[dict] = None) -> dict:
    """对已打开的素材文档就地做全部预处理。

    合并链路直接用这个入口：素材只打开一次，预处理、标题映射和 section 隔离都在
    同一份内存文档上完成，不再落中间文件反复重开。
    """
    style_prune = prune_unused_styles(doc)
    stats = {
        "styles_pruned": style_prune["removed"],
        # 素材标题样式在编号阶段按有效 outline/basedOn 识别，这里不再改写样式。
        "heading_by_outline": 0,
        "heading_normalize": 0,
        "numPr_stripped": strip_numPr_from_body(doc),
        "heading_prefix_strip": 0,
        "body_handwritten_strip": strip_handwritten_numbering_in_body(doc, only_normal_style=True),
        "tag_strip": strip_tag_marks(doc),
        "placeholder_replace": replace_placeholders(doc, params or {}),
    }
    stats.update(sanitize_dangling_media_refs(doc))
    return stats


def preprocess(
    in_path: Path,
    out_path: Path,
    params: Optional[dict] = None,
    *,
    verbose: bool = False,
) -> dict:
    doc = Document(str(in_path))
    stats = preprocess_doc(doc, params)

    os.makedirs(os.fspath(out_path.parent), exist_ok=True)
    doc.save(str(out_path))

    if verbose:
        print(f"  preprocess {in_path.name}: {stats}", file=sys.stderr)

    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--params", type=Path, default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    params = {}
    if args.params and args.params.exists():
        params = json.loads(args.params.read_text(encoding="utf-8"))

    stats = preprocess(args.input, args.output, params, verbose=args.verbose)
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
