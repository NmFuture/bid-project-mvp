#!/usr/bin/env python3
"""
生成技术投标母版模板 docx。

策略：
1. 以 投标文件-正文.docx 为基（已带多级列表 numbering、Heading 1-6 样式、页眉 logo）
2. 清空 body，只保留最后一个 sectPr（即只保留第一节的页面设置）
3. 按 heading_style.json 覆写 Heading 1-6 的字体/字号/段落参数
4. 清理未被 headers 引用的 media 文件，显著缩小体积
5. 页面边距按 heading_style.json 覆写

输出：<skill_dir>/templates/技术投标母版模板.docx

用法：
    python3 tools/create_tech_master.py [--sample 投标文件-正文.docx] [--style heading_style.json] [--out 技术投标母版模板.docx]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import nsmap, qn
from docx.shared import Cm, Pt

# ---------- 默认路径 ----------

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLE = Path("/Users/wlb/Downloads/技术标/招投标模板/投标文件-正文.docx")
DEFAULT_STYLE = SKILL_DIR / "references" / "heading_style.json"
DEFAULT_OUT = SKILL_DIR / "templates" / "技术投标母版模板.docx"


# ---------- 对齐映射 ----------

ALIGN_MAP = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "both": WD_ALIGN_PARAGRAPH.JUSTIFY,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}


# ---------- Step 1: body 清空 ----------

def strip_body(doc: Document) -> None:
    """清空 body：删除所有 paragraph/table，保留最后一个 sectPr；只留 1 个空段。"""
    body = doc.element.body
    sect_pr = body.find(qn("w:sectPr"))
    if sect_pr is None:
        raise RuntimeError("body 缺 sectPr，模板异常")

    # 移除所有非 sectPr 子元素
    for child in list(body):
        if child is sect_pr:
            continue
        body.remove(child)

    # 加一个空段落，放在 sectPr 之前
    p = OxmlElement("w:p")
    body.insert(0, p)


# ---------- Step 2: 页面设置 ----------

def apply_page_setup(doc: Document, page_cfg: dict) -> None:
    sec = doc.sections[0]
    sec.top_margin = Cm(page_cfg["top_cm"])
    sec.bottom_margin = Cm(page_cfg["bottom_cm"])
    sec.left_margin = Cm(page_cfg["left_cm"])
    sec.right_margin = Cm(page_cfg["right_cm"])
    sec.header_distance = Cm(page_cfg["header_top_cm"])
    sec.footer_distance = Cm(page_cfg["footer_bottom_cm"])


# ---------- Step 3: Heading / 正文样式覆写 ----------

def _set_rFonts(rPr_el, zh_font: str, en_font: str) -> None:
    """rPr 下注入 w:rFonts。"""
    rFonts = rPr_el.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr_el.insert(0, rFonts)
    rFonts.set(qn("w:ascii"), en_font)
    rFonts.set(qn("w:hAnsi"), en_font)
    rFonts.set(qn("w:cs"), en_font)
    rFonts.set(qn("w:eastAsia"), zh_font)


def _set_or_replace_child(parent, tag: str, attrs: dict) -> None:
    """替换 parent 下的 w:tag 元素（只有一个）。"""
    existing = parent.find(qn(tag))
    if existing is not None:
        parent.remove(existing)
    new = OxmlElement(tag)
    for k, v in attrs.items():
        new.set(qn(k), v)
    parent.append(new)


def _get_or_create_child(parent, tag: str, insert_first: bool = True):
    el = parent.find(qn(tag))
    if el is not None:
        return el
    el = OxmlElement(tag)
    if insert_first:
        parent.insert(0, el)
    else:
        parent.append(el)
    return el


def apply_style_overrides(doc: Document, style_cfg: dict) -> None:
    """逐级覆写 Heading 1-6 及 Normal/正文 样式的 rPr / pPr。"""
    styles = doc.styles

    # Heading 1-6
    for lvl in range(1, 7):
        style_name = f"Heading {lvl}"
        try:
            style = styles[style_name]
        except KeyError:
            # 没有就创建（极少见）
            from docx.enum.style import WD_STYLE_TYPE
            style = styles.add_style(style_name, WD_STYLE_TYPE.PARAGRAPH)
            style.base_style = None
        _apply_heading_style(style, style_cfg["heading"][str(lvl)])

    # Normal（正文）
    try:
        normal = styles["Normal"]
        _apply_body_style(normal, style_cfg["body"])
    except KeyError:
        pass


def _apply_heading_style(style, cfg: dict) -> None:
    elem = style.element  # w:style
    rPr = _get_or_create_child(elem, "w:rPr")
    pPr = _get_or_create_child(elem, "w:pPr")

    # rPr: 字体、字号、粗体
    _set_rFonts(rPr, cfg["zh_font"], cfg["en_font"])
    half = int(cfg["size_pt"] * 2)
    _set_or_replace_child(rPr, "w:sz", {"w:val": str(half)})
    _set_or_replace_child(rPr, "w:szCs", {"w:val": str(half)})
    if cfg.get("bold"):
        _set_or_replace_child(rPr, "w:b", {})
        _set_or_replace_child(rPr, "w:bCs", {})

    # pPr: 对齐、段距、行距、缩进
    align_val = {"left": "left", "center": "center", "right": "right", "both": "both", "justify": "both"}.get(
        cfg.get("align", "left"), "left"
    )
    _set_or_replace_child(pPr, "w:jc", {"w:val": align_val})

    # 段前段后（pt → 1/20 pt = twentieths = *20）
    space_attrs = {
        "w:before": str(int(cfg["space_before_pt"] * 20)),
        "w:after": str(int(cfg["space_after_pt"] * 20)),
    }
    # 行距：multiple line
    ls = cfg.get("line_spacing", 1.5)
    space_attrs["w:line"] = str(int(ls * 240))  # 240 = 单倍
    space_attrs["w:lineRule"] = "auto"
    _set_or_replace_child(pPr, "w:spacing", space_attrs)

    # 缩进
    ind_attrs = {}
    if cfg.get("first_line_indent_chars"):
        ind_attrs["w:firstLineChars"] = str(int(cfg["first_line_indent_chars"] * 100))
    if cfg.get("left_indent_cm"):
        ind_attrs["w:leftChars"] = "0"
        ind_attrs["w:left"] = str(int(cfg["left_indent_cm"] * 567))  # cm → twips ≈ ×567
    if ind_attrs:
        _set_or_replace_child(pPr, "w:ind", ind_attrs)


def _apply_body_style(style, cfg: dict) -> None:
    elem = style.element
    rPr = _get_or_create_child(elem, "w:rPr")
    pPr = _get_or_create_child(elem, "w:pPr")

    _set_rFonts(rPr, cfg["zh_font"], cfg["en_font"])
    half = int(cfg["size_pt"] * 2)
    _set_or_replace_child(rPr, "w:sz", {"w:val": str(half)})
    _set_or_replace_child(rPr, "w:szCs", {"w:val": str(half)})

    align_val = {"left": "left", "center": "center", "both": "both", "justify": "both"}.get(
        cfg.get("align", "both"), "both"
    )
    _set_or_replace_child(pPr, "w:jc", {"w:val": align_val})

    ls = cfg.get("line_spacing", 1.5)
    _set_or_replace_child(pPr, "w:spacing", {
        "w:before": str(int(cfg["space_before_pt"] * 20)),
        "w:after": str(int(cfg["space_after_pt"] * 20)),
        "w:line": str(int(ls * 240)),
        "w:lineRule": "auto",
    })

    if cfg.get("first_line_indent_chars"):
        _set_or_replace_child(pPr, "w:ind", {
            "w:firstLineChars": str(int(cfg["first_line_indent_chars"] * 100)),
        })


# ---------- Step 4: zip 级部件图闭包剪枝 ----------

def _resolve_target(source: str, target: str) -> str:
    """rel source part 路径 + target (相对路径) → 规范化 zip 内路径。

    - source='_rels/.rels' → base=''
    - source='word/_rels/document.xml.rels' → base='word'
    - source='word/charts/_rels/chart1.xml.rels' → base='word/charts'
    - target 以 '/' 开头 → 绝对路径（去前缀 /）
    """
    if target.startswith("/"):
        return target.lstrip("/")

    # 从 rels 文件路径剥出 base dir：去掉尾部 "/base.rels"，去掉 "_rels" 这一段
    if source.endswith(".rels"):
        # 去掉 "/xxx.rels" 尾部
        dir_only = source.rsplit("/", 1)[0]  # e.g. "_rels" 或 "word/_rels" 或 "word/charts/_rels"
        # 剥掉末尾的 "_rels"
        if dir_only == "_rels":
            base = ""
        elif dir_only.endswith("/_rels"):
            base = dir_only[: -len("/_rels")]
        else:
            base = dir_only
    else:
        base = source.rsplit("/", 1)[0]

    # 拼接并规范化
    combined = (base + "/" + target) if base else target
    parts = combined.split("/")
    out: list[str] = []
    for p in parts:
        if p == "." or p == "":
            continue
        elif p == "..":
            if out:
                out.pop()
        else:
            out.append(p)
    return "/".join(out)


def _cleanup_orphan_rels(docx_path: Path) -> None:
    """清理 .rels 文件里未被对应 part 真正引用的 Relationship。

    对 part X 的 rels 文件 X.rels，收集 X 里出现的所有 r:id/r:embed/r:link/r:link 等
    rId 值，仅保留这些 rId 的 Relationship 条目。
    """
    ID_ATTR_PATTERN = re.compile(r'(?:r:id|r:embed|r:link|id)="(rId\d+)"')

    with zipfile.ZipFile(docx_path, "r") as zin:
        names = zin.namelist()
        data = {n: zin.read(n) for n in names}

    changed = False
    for rels_name in list(data.keys()):
        if not rels_name.endswith(".rels"):
            continue
        # 对应的 part 文件
        dir_only = rels_name.rsplit("/", 1)[0]
        base = rels_name.rsplit("/", 1)[1][: -len(".rels")]  # e.g. "document.xml"
        if dir_only == "_rels":
            part_name = base
        elif dir_only.endswith("/_rels"):
            part_name = dir_only[: -len("/_rels")] + "/" + base
        else:
            continue

        if part_name not in data:
            continue

        # 收集 part 里真正用到的 rId
        try:
            part_text = data[part_name].decode("utf-8", errors="replace")
        except Exception:
            continue
        used_ids = set(ID_ATTR_PATTERN.findall(part_text))

        # 过滤 rels
        rels_text = data[rels_name].decode("utf-8", errors="replace")
        def keep_rel(match: "re.Match") -> str:
            full = match.group(0)
            rid_m = re.search(r'Id="([^"]+)"', full)
            tgt_m = re.search(r'Target="([^"]+)"', full)
            if not rid_m:
                return full
            rid = rid_m.group(1)
            # 指向 header/footer/theme/styles/numbering/settings/fontTable/webSettings 等结构件不能丢
            if tgt_m:
                tgt = tgt_m.group(1)
                if any(k in tgt for k in (
                    "header", "footer", "theme", "styles", "numbering",
                    "settings", "fontTable", "webSettings", "glossary",
                    "customXml", "endnotes", "footnotes", "comments",
                    "people", "commentsExtended", "commentsIds",
                )):
                    return full
            if rid in used_ids:
                return full
            return ""

        new_text = re.sub(r'<Relationship\b[^>]*?/>', keep_rel, rels_text)
        if new_text != rels_text:
            data[rels_name] = new_text.encode("utf-8")
            changed = True

    if not changed:
        return

    tmp = docx_path.with_suffix(".relsclean.docx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            zout.writestr(name, data[name])
    shutil.move(str(tmp), str(docx_path))


def prune_unreferenced_media(docx_path: Path) -> tuple[int, int]:
    """部件图闭包剪枝：从 document.xml 出发，保留所有可达部件，其余删除。"""

    # Step 0: 先清理 rels 里的孤儿条目（没被对应 part 引用的）
    _cleanup_orphan_rels(docx_path)

    with zipfile.ZipFile(docx_path, "r") as zin:
        names = set(zin.namelist())

        # 始终保留
        always_keep = {
            "[Content_Types].xml",
            "_rels/.rels",
        }
        always_keep.update(n for n in names if n.startswith("docProps/"))
        always_keep.update(n for n in names if n.startswith("customXml/"))

        # 闭包遍历
        keep: set[str] = set(always_keep)
        # 从根 rels 展开一次，找到 document.xml 和其它根入口
        root_rels = zin.read("_rels/.rels").decode("utf-8", errors="replace")
        queue: list[str] = []
        for m in re.finditer(r'Target="([^"]+)"', root_rels):
            tgt = _resolve_target("_rels/.rels", m.group(1))
            if tgt in names:
                queue.append(tgt)
                keep.add(tgt)

        while queue:
            part = queue.pop()
            # 该 part 的 rels 文件
            if "/" in part:
                dir_, base = part.rsplit("/", 1)
                rels_name = f"{dir_}/_rels/{base}.rels"
            else:
                rels_name = f"_rels/{part}.rels"

            if rels_name not in names:
                continue
            keep.add(rels_name)
            try:
                text = zin.read(rels_name).decode("utf-8", errors="replace")
            except Exception:
                continue
            for m in re.finditer(r'Target="([^"]+)"', text):
                tgt_raw = m.group(1)
                # 外链跳过
                if tgt_raw.startswith("http://") or tgt_raw.startswith("https://"):
                    continue
                tgt = _resolve_target(rels_name, tgt_raw)
                if tgt in names and tgt not in keep:
                    keep.add(tgt)
                    queue.append(tgt)

        to_remove = [n for n in names if n not in keep]
        freed = sum(zin.getinfo(n).file_size for n in to_remove)

        tmp_out = docx_path.with_suffix(".pruned.docx")
        with zipfile.ZipFile(tmp_out, "w", zipfile.ZIP_DEFLATED) as zout:
            for name in keep:
                zout.writestr(zin.getinfo(name), zin.read(name))

    # Content_Types.xml 可能引用已删除的部件扩展名；简单起见不改，多数 consumer 容忍
    # 但要修 document.xml.rels 去除指向已删除部件的 rel
    _fix_rels_after_prune(tmp_out, keep)

    shutil.move(str(tmp_out), str(docx_path))
    return len(to_remove), freed


def _fix_rels_after_prune(docx_path: Path, keep: set[str]) -> None:
    """把 .rels 里指向已删除部件的 Relationship 条目干掉。"""
    with zipfile.ZipFile(docx_path, "r") as zin:
        names = zin.namelist()
        data = {n: zin.read(n) for n in names}

    changed = False
    for name in list(data.keys()):
        if not name.endswith(".rels"):
            continue
        text = data[name].decode("utf-8", errors="replace")

        def drop_if_gone(match: "re.Match") -> str:
            full = match.group(0)
            tgt_m = re.search(r'Target="([^"]+)"', full)
            if not tgt_m:
                return full
            tgt = tgt_m.group(1)
            if tgt.startswith("http://") or tgt.startswith("https://"):
                return full
            resolved = _resolve_target(name, tgt)
            if resolved in keep:
                return full
            return ""

        new_text = re.sub(r'<Relationship\b[^>]*?/>', drop_if_gone, text)
        if new_text != text:
            data[name] = new_text.encode("utf-8")
            changed = True

    if not changed:
        return

    tmp_out = docx_path.with_suffix(".relsfix.docx")
    with zipfile.ZipFile(tmp_out, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, raw in data.items():
            zout.writestr(name, raw)
    shutil.move(str(tmp_out), str(docx_path))


# ---------- Step 5: 页眉文本占位 ----------

HEADER_PLACEHOLDER = "{project_name}投标文件-技术部分"


def inject_header_placeholder(docx_path: Path) -> None:
    """把 header*.xml 里的可见文字段替换为占位符；finalize.py 会替换真实项目名。

    简化策略：只记录占位符，不改 header XML 结构（保留 logo 图片）。
    finalize.py 按项目名搜索替换。
    """
    # 先不动；finalize 阶段基于文本正则替换。此处仅做 sanity 打印。
    with zipfile.ZipFile(docx_path, "r") as z:
        for name in z.namelist():
            if not name.startswith("word/header") or not name.endswith(".xml"):
                continue
            content = z.read(name).decode("utf-8", errors="replace")
            # 抽可见文字
            texts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", content)
            joined = "".join(texts)[:80]
            if joined:
                print(f"  [header] {name}: {joined!r}")


# ---------- Main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    ap.add_argument("--style", type=Path, default=DEFAULT_STYLE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    if not args.sample.exists():
        print(f"[ERR] sample not found: {args.sample}", file=sys.stderr)
        sys.exit(1)
    if not args.style.exists():
        print(f"[ERR] style spec not found: {args.style}", file=sys.stderr)
        sys.exit(1)

    style_cfg = json.loads(args.style.read_text(encoding="utf-8"))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    print(f"[1/5] 复制样例 → {args.out}")
    shutil.copy(str(args.sample), str(args.out))
    size_before = args.out.stat().st_size / 1024 / 1024
    print(f"      copy size: {size_before:.1f} MB")

    print("[2/5] 清空 body")
    doc = Document(str(args.out))
    strip_body(doc)

    print("[3/5] 页面设置")
    apply_page_setup(doc, style_cfg["page"])

    print("[4/5] 覆写 Heading 1-6 + Normal 样式")
    apply_style_overrides(doc, style_cfg)

    doc.save(str(args.out))
    size_stripped = args.out.stat().st_size / 1024 / 1024
    print(f"      stripped size: {size_stripped:.1f} MB")

    print("[5/5] 清理未引用 media")
    removed, freed = prune_unreferenced_media(args.out)
    size_final = args.out.stat().st_size / 1024 / 1024
    print(f"      removed {removed} files, freed {freed/1024/1024:.1f} MB")
    print(f"      final size: {size_final:.1f} MB")

    print()
    print("页眉检查:")
    inject_header_placeholder(args.out)

    # sanity: 能否正常打开
    _ = Document(str(args.out))
    print()
    print(f"OK: {args.out}")


if __name__ == "__main__":
    main()
