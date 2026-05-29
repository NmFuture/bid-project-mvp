#!/usr/bin/env python3
"""
终检打磨：

1. 开篇插 Word TOC 域（Heading 1 "目录" + { TOC \\o "1-5" \\h \\z \\u } + updateFields=true）
2. 按 heading_style.json 再刷 Heading 1-6 的 rFonts（兜底）
3. 页眉项目名替换：把 header*.xml 中残留样例项目名替换为 project_params.project_name
4. 页眉后缀兼容：如遇 "投标文件-技术卷" 全局替换为 "投标文件-技术部分"
5. 强制 Word 打开时刷新域（settings.xml 注入 w:updateFields）

用法：
    python3 finalize.py \\
        --in /tmp/bid_merged.docx \\
        --params project_params.json \\
        --style references/heading_style.json \\
        --out 投标文件-正文_<简称>_<时间戳>.docx
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import shutil
import zipfile
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from numbering_fixer import strip_numPr_from_body, strip_numPr_from_heading_styles


# ---------- Step 1: 插 TOC 域 ----------

def insert_toc_field(doc: Document) -> None:
    """在 body 最前面插入 Heading 1 "目录" + TOC 域 + 分页符。"""
    body = doc.element.body

    def _make_p(text: str, style_id: str = None) -> OxmlElement:
        p = OxmlElement("w:p")
        if style_id:
            pPr = OxmlElement("w:pPr")
            pStyle = OxmlElement("w:pStyle")
            pStyle.set(qn("w:val"), style_id)
            pPr.append(pStyle)
            p.append(pPr)
        r = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = text
        r.append(t)
        p.append(r)
        return p

    def _make_toc_field_paragraph() -> OxmlElement:
        p = OxmlElement("w:p")
        # 开始域
        r1 = OxmlElement("w:r")
        fld_begin = OxmlElement("w:fldChar")
        fld_begin.set(qn("w:fldCharType"), "begin")
        r1.append(fld_begin)
        p.append(r1)
        # 指令
        r2 = OxmlElement("w:r")
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = ' TOC \\o "1-5" \\h \\z \\u '
        r2.append(instr)
        p.append(r2)
        # 分隔
        r3 = OxmlElement("w:r")
        fld_sep = OxmlElement("w:fldChar")
        fld_sep.set(qn("w:fldCharType"), "separate")
        r3.append(fld_sep)
        p.append(r3)
        # 占位文字
        r4 = OxmlElement("w:r")
        t4 = OxmlElement("w:t")
        t4.text = "目录（请在 Word 中按 F9 或打开文件时自动更新）"
        r4.append(t4)
        p.append(r4)
        # 结束
        r5 = OxmlElement("w:r")
        fld_end = OxmlElement("w:fldChar")
        fld_end.set(qn("w:fldCharType"), "end")
        r5.append(fld_end)
        p.append(r5)
        return p

    def _make_page_break() -> OxmlElement:
        p = OxmlElement("w:p")
        r = OxmlElement("w:r")
        br = OxmlElement("w:br")
        br.set(qn("w:type"), "page")
        r.append(br)
        p.append(r)
        return p

    # TOC 域应插在封面之后、第一个 Heading 段之前
    # 识别：body 里第一个含有 pStyle 且样式名为 Heading/标题 的段落
    def _is_heading_para(el) -> bool:
        if el.tag != qn("w:p"):
            return False
        pPr = el.find(qn("w:pPr"))
        if pPr is None:
            return False
        pStyle = pPr.find(qn("w:pStyle"))
        if pStyle is None:
            return False
        val = pStyle.get(qn("w:val")) or ""
        # 母版里 Heading 1 的 styleId 可能是 "10"/"2"/"3" 等数字；按 styleName 查太复杂
        # 这里宽松判断：styleId 为单个数字或含 'heading'/'标题' 关键字
        return val in ("10", "2", "3", "4", "5", "6", "7", "8", "9") or \
               "eading" in val.lower() or val.startswith("标题")

    anchor = None
    for child in list(body):
        if child.tag == qn("w:sectPr"):
            break
        if _is_heading_para(child):
            anchor = child
            break

    # 封面之后分页 → "目录" 标题 → TOC 域 → 分页符 → 前言
    # "目录" 用 "TOC Heading"（styleId="TOC"），它本身不进 TOC 域的目录项
    p_cover_break = _make_page_break()
    p_title = _make_p("目录", style_id="TOC")
    p_toc = _make_toc_field_paragraph()
    p_break = _make_page_break()

    insert_sequence = (p_cover_break, p_title, p_toc, p_break)
    if anchor is not None:
        # 在 anchor 前依次插入
        for el in insert_sequence:
            anchor.addprevious(el)
    else:
        # 无 Heading，退化为 body 最前
        first_non_sect = None
        for child in list(body):
            if child.tag != qn("w:sectPr"):
                first_non_sect = child
                break
        for el in reversed(insert_sequence):
            if first_non_sect is not None:
                first_non_sect.addprevious(el)
            else:
                body.insert(0, el)


# ---------- Step 2: 强制更新域 ----------

def force_update_fields(docx_path: Path) -> None:
    """在 word/settings.xml 注入 <w:updateFields w:val="true"/>，让 Word 打开时自动更新 TOC 域。"""
    with zipfile.ZipFile(docx_path, "r") as zin:
        names = zin.namelist()
        data = {n: zin.read(n) for n in names}

    if "word/settings.xml" not in data:
        return

    text = data["word/settings.xml"].decode("utf-8", errors="replace")
    if "<w:updateFields" in text:
        return  # 已有

    # 注入到 <w:settings> 根下
    text = re.sub(
        r"(<w:settings[^>]*>)",
        r'\1<w:updateFields w:val="true"/>',
        text,
        count=1,
    )
    data["word/settings.xml"] = text.encode("utf-8")

    tmp = docx_path.with_suffix(".tmp.docx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            zout.writestr(name, data[name])
    shutil.move(str(tmp), str(docx_path))


# ---------- Step 3: 页眉文本替换 ----------

def replace_header_text(docx_path: Path, project_name: str) -> None:
    """替换所有 word/header*.xml 里的页眉文字。

    策略：
      - 把 '投标文件-技术卷' → '投标文件-技术部分'
      - 把样例项目名 '华能蒙东...基地项目' 替换为 project_name
      - 如 header 里存在非 project_name 的中文项目句，替换为 {project_name}投标文件-技术部分
    """
    with zipfile.ZipFile(docx_path, "r") as zin:
        names = zin.namelist()
        data = {n: zin.read(n) for n in names}

    changed = False
    # 已知要替换的关键片段
    replacements = [
        ("投标文件-技术卷", "投标文件-技术部分"),
    ]

    for name in list(data.keys()):
        if not (name.startswith("word/header") and name.endswith(".xml")):
            continue
        text = data[name].decode("utf-8", errors="replace")

        # 把所有连续 w:t 的文本抽出来拼一下看
        joined = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", text))

        new_text = text
        for old, new in replacements:
            new_text = new_text.replace(old, new)

        # 如果页眉里有老项目名（含"投标文件"且长度 > 20 的中文串），且包含"投标文件"，替换为新的
        # 简化：若全文包含非 project_name 的"华能...投标文件" 之类，逐个 w:t 检查并替换
        if project_name and project_name not in joined:
            # 把 w:t 文本一个个检查：若文本包含"投标文件"且不是 project_name 已包含，替换整条 w:t
            def _replace_wt(match: "re.Match") -> str:
                inner = match.group(2)
                if "投标文件" in inner and project_name not in inner:
                    return f"{match.group(1)}{project_name}投标文件-技术部分{match.group(3)}"
                return match.group(0)

            new_text = re.sub(
                r"(<w:t[^>]*>)([^<]*)(</w:t>)",
                _replace_wt,
                new_text,
            )

        if new_text != text:
            data[name] = new_text.encode("utf-8")
            changed = True

    if not changed:
        return

    tmp = docx_path.with_suffix(".hdr.docx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            zout.writestr(name, data[name])
    shutil.move(str(tmp), str(docx_path))


# ---------- Step 4: Heading rFonts 兜底刷 ----------

def reapply_heading_fonts(doc: Document, style_cfg: dict) -> None:
    """兜底：把 Heading 1-6 style 的 rFonts / sz 再写一遍，对付素材合并后 style merge 的覆盖。"""
    styles = doc.styles
    for lvl in range(1, 7):
        name = f"Heading {lvl}"
        try:
            style = styles[name]
        except KeyError:
            continue
        cfg = style_cfg["heading"].get(str(lvl))
        if not cfg:
            continue
        rPr = style.element.find(qn("w:rPr"))
        if rPr is None:
            rPr = OxmlElement("w:rPr")
            style.element.insert(0, rPr)
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is None:
            rFonts = OxmlElement("w:rFonts")
            rPr.insert(0, rFonts)
        rFonts.set(qn("w:eastAsia"), cfg["zh_font"])
        rFonts.set(qn("w:ascii"), cfg["en_font"])
        rFonts.set(qn("w:hAnsi"), cfg["en_font"])
        rFonts.set(qn("w:cs"), cfg["en_font"])
        # sz
        half = str(int(cfg["size_pt"] * 2))
        for tag in ("w:sz", "w:szCs"):
            el = rPr.find(qn(tag))
            if el is None:
                el = OxmlElement(tag)
                rPr.append(el)
            el.set(qn("w:val"), half)


# ---------- Main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", type=Path, required=True)
    ap.add_argument("--params", type=Path, required=True)
    ap.add_argument("--style", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    params = json.loads(args.params.read_text(encoding="utf-8"))
    style_cfg = json.loads(args.style.read_text(encoding="utf-8"))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(args.inp), str(args.out))

    # python-docx 阶段：插 TOC 域 + 刷 Heading 样式
    doc = Document(str(args.out))
    insert_toc_field(doc)
    reapply_heading_fonts(doc, style_cfg)
    strip_numPr_from_heading_styles(doc)
    strip_numPr_from_body(doc)
    doc.save(str(args.out))

    # zip 阶段：改页眉文字 + 注入 updateFields
    project_name = params.get("project_name") or ""
    if project_name:
        replace_header_text(args.out, project_name)
    force_update_fields(args.out)

    print(f"[OK] {args.out} ({args.out.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
