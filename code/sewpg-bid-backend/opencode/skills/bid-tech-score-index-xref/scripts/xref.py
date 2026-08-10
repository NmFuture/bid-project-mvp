# -*- coding: utf-8 -*-
"""
技术标「技术评分标准索引表」章节索引列 —— 交叉引用 + 页码 工具

三个子命令：
    inspect  导出标题结构 + 索引表各行原文，供判断该填哪些章节
    build    填写章节索引列（可选）+ 建立交叉引用和页码
    verify   校验成品的完整性

最终效果，每条形如：

    5.1 投标总体方案概述，P213
    └────── 超链接跳转 ─────┘  └ PAGEREF 域，F9 自动刷新

全部使用 Word 原生机制（书签 + 内部超链接 + PAGEREF 域），不写死页码。

依赖：lxml；pywin32（仅 Windows 上自动算页码时需要，可选）

本模块同时是库：`build_xref` / `verify_xref` / `inspect_docx` 返回结构化结果，
命令行只负责打印，后端 `run_from_manifest.py` 直接调用库函数。
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
import zipfile
from collections import defaultdict

from lxml import etree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

# 默认识别关键字。不同项目表头措辞可能不同，可用命令行参数覆盖，不必改代码。
DEFAULT_INDEX_HEADERS = ["章节索引", "章节索引表", "对应章节", "响应章节", "索引"]
DEFAULT_FACTOR_HEADERS = ["评审因素", "评分因素", "评审要素", "评分要素", "评分项"]
PAGE_PREFIX = "，P"
PAGE_PLACEHOLDER = "0"
BOOKMARK_PREFIX = "_Xref_"


class XrefError(Exception):
    """交叉引用工具的可预期失败。"""


class IndexTableNotFound(XrefError):
    """文档里没有可识别的评分索引表。"""


class MappingUnresolved(XrefError):
    """映射里的章节在正文中找不到或不唯一。"""

    def __init__(self, missing: list):
        self.missing = missing
        detail = "；".join(f"[{factor}] -> {ref}" for factor, ref in missing)
        super().__init__(f"以下章节在正文中找不到（或不唯一）：{detail}")


def w(tag: str) -> str:
    return W + tag


# --------------------------------------------------------------------------
# 通用工具
# --------------------------------------------------------------------------
def text_of(el) -> str:
    return "".join(t.text or "" for t in el.iter(w("t")))


def norm(s: str) -> str:
    """归一化：去掉全部空白，去掉首尾标点。用于宽松匹配。"""
    s = (s or "").replace("　", " ")
    s = re.sub(r"\s+", "", s)
    return s.strip(" 　:：。.、,，;；")


# 条目开头的编号：`第4章` / `5.1` / `5.8.16`
NUM_RE = re.compile(r"^\s*(?P<num>第\s*\d+\s*章|\d+(?:\.\d+)*)\s*(?P<title>.*)$")
# 已加过的 "，P123" 尾巴，用于幂等重跑
TAIL_RE = re.compile(r"[，,]\s*[Pp]\s*\d*\s*$")


def split_entry(raw: str):
    """'5.1 投标总体方案概述' -> ('5.1', '投标总体方案概述', 去尾原文)"""
    s = TAIL_RE.sub("", (raw or "").strip())
    m = NUM_RE.match(s)
    if m and m.group("title"):
        return m.group("num"), m.group("title"), s
    return None, s, s


def clean_title(s: str) -> str:
    return s.rstrip("：: 　")


# --------------------------------------------------------------------------
# 标题结构解析
# --------------------------------------------------------------------------
class Heading:
    __slots__ = ("el", "level", "number", "title", "bookmark")

    def __init__(self, el, level, number, title):
        self.el, self.level, self.number, self.title = el, level, number, title
        self.bookmark = None

    @property
    def display(self) -> str:
        return f"{self.number} {self.title}" if self.number else self.title


def build_heading_styles(styles_root) -> dict:
    """{styleId: level}。按样式名识别，不依赖具体 styleId（各文档不同）。"""
    out = {}
    name_re = re.compile(r"^\s*(?:heading|标题)\s*([1-9])\s*$", re.I)
    for st in styles_root.iter(w("style")):
        if st.get(w("type")) not in (None, "paragraph"):
            continue
        sid = st.get(w("styleId"))
        nm_el = st.find(w("name"))
        nm = nm_el.get(w("val")) if nm_el is not None else ""
        m = name_re.match(nm or "")
        if m:
            out[sid] = int(m.group(1))
            continue
        outl = st.find(w("pPr") + "/" + w("outlineLvl"))
        if outl is not None and re.search(r"heading|标题", nm or "", re.I):
            out[sid] = int(outl.get(w("val"))) + 1
    return out


def style_num_ids(styles_root, heading_styles) -> dict:
    """标题编号通常挂在样式上而非段落上。"""
    out = {}
    for st in styles_root.iter(w("style")):
        sid = st.get(w("styleId"))
        if sid in heading_styles:
            ni = st.find(w("pPr") + "/" + w("numPr") + "/" + w("numId"))
            if ni is not None:
                out[sid] = ni.get(w("val"))
    return out


def numbering_formats(numbering_root) -> dict:
    """{numId: {ilvl: lvlText}}，还原 '第%1章 ' / '%1.%2' 这类格式。"""
    if numbering_root is None:
        return {}
    abstract = {}
    for an in numbering_root.iter(w("abstractNum")):
        lvls = {}
        for lvl in an.findall(w("lvl")):
            t = lvl.find(w("lvlText"))
            if t is not None:
                lvls[int(lvl.get(w("ilvl")))] = t.get(w("val"))
        abstract[an.get(w("abstractNumId"))] = lvls
    out = {}
    for n in numbering_root.iter(w("num")):
        ai = n.find(w("abstractNumId"))
        if ai is not None:
            out[n.get(w("numId"))] = abstract.get(ai.get(w("val")), {})
    return out


def render_number(fmt: str, counters: list, level: int) -> str:
    if not fmt:
        return ".".join(str(counters[i]) for i in range(level))
    s = fmt
    for i in range(9, 0, -1):
        s = s.replace(f"%{i}", str(counters[i - 1]) if i <= level else "")
    return s.strip()


def _heading_without_auto_number(p, level, title) -> Heading:
    """没有 Word 自动编号的标题：若正文文字自带编号，拆成 number + title。

    技术标成稿走「文本编号 + Heading 样式」，格式清洗还会主动抑制自动编号，
    所以正文里绝大多数标题都落到这一支；不拆的话映射只能写整条标题。
    """
    num, rest, _ = split_entry(title)
    if num:
        return Heading(p, level, num, rest)
    return Heading(p, level, None, title)


def scan_headings(body, heading_styles, snumids, numfmts, skip_els: set) -> list:
    """按文档顺序扫描标题，复算 Word 的自动编号。"""
    headings = []
    counters = defaultdict(lambda: [0] * 9)  # 每条编号链各自计数

    for p in body.iter(w("p")):
        if p in skip_els:
            continue
        pPr = p.find(w("pPr"))
        if pPr is None:
            continue
        st = pPr.find(w("pStyle"))
        sid = st.get(w("val")) if st is not None else None
        level = heading_styles.get(sid)
        if not level:
            continue
        title = text_of(p).strip()
        if not title:
            continue

        num_id, ilvl_override = None, None
        npr = pPr.find(w("numPr"))
        if npr is not None:
            ni, il = npr.find(w("numId")), npr.find(w("ilvl"))
            if ni is not None:
                num_id = ni.get(w("val"))
            if il is not None:
                ilvl_override = int(il.get(w("val")))
        if num_id is None:
            num_id = snumids.get(sid)

        # numId=0 是段落级"取消编号"，常见于附表类标题和技术标成稿的文本编号标题
        if num_id in (None, "0"):
            headings.append(_heading_without_auto_number(p, level, title))
            continue

        lvl = max(1, min((ilvl_override + 1) if ilvl_override is not None else level, 9))
        c = counters[num_id]
        c[lvl - 1] += 1
        for k in range(lvl, 9):
            c[k] = 0
        headings.append(Heading(p, level, render_number(numfmts.get(num_id, {}).get(lvl - 1), c, lvl), title))
    return headings


# --------------------------------------------------------------------------
# 索引表定位
# --------------------------------------------------------------------------
def cell_text(tc) -> str:
    return "\n".join(text_of(p) for p in tc.findall(w("p")))


def find_index_table(body, index_headers, factor_headers):
    """返回 (tbl, 章节索引列号, 评审因素列号)。"""
    for tbl in body.iter(w("tbl")):
        rows = tbl.findall(w("tr"))
        if not rows:
            continue
        texts = [norm(cell_text(c)) for c in rows[0].findall(w("tc"))]
        joined = "".join(texts)
        if not any(norm(s) in joined for s in factor_headers):
            continue  # 不是评分表，跳过
        col = next((i for i, t in enumerate(texts) if any(norm(h) == t for h in index_headers)), None)
        if col is None:
            continue
        fac = next((i for i, t in enumerate(texts) if any(norm(h) == t for h in factor_headers)), None)
        return tbl, col, fac
    return None, None, None


def load_doc(path):
    with zipfile.ZipFile(path) as z:
        doc = etree.fromstring(z.read("word/document.xml"))
        sty = etree.fromstring(z.read("word/styles.xml"))
        try:
            nbr = etree.fromstring(z.read("word/numbering.xml"))
        except KeyError:
            nbr = None
    return doc, sty, nbr


def prepare(path, index_headers, factor_headers):
    """统一入口：返回 (doc_root, body, tbl, col, fac, headings)。"""
    doc, sty, nbr = load_doc(path)
    body = doc.find(w("body"))
    tbl, col, fac = find_index_table(body, index_headers, factor_headers)
    if tbl is None:
        raise IndexTableNotFound(
            "未找到评分索引表。请用 --index-header / --factor-header 指定该文件的表头措辞。"
        )
    hs = build_heading_styles(sty)
    headings = scan_headings(body, hs, style_num_ids(sty, hs), numbering_formats(nbr),
                             set(tbl.iter(w("p"))))
    return doc, body, tbl, col, fac, headings


# --------------------------------------------------------------------------
# 章节映射解析：把「章节号或标题」统一解析成正文中的真实标题
# --------------------------------------------------------------------------
def build_lookups(headings):
    by_num, by_title, by_full = {}, defaultdict(list), {}
    for h in headings:
        if h.number:
            by_num.setdefault(norm(h.number), h)
        by_title[norm(h.title)].append(h)
        by_full.setdefault(norm(h.display), h)
    return by_num, by_title, by_full


def find_heading(ref: str, by_num, by_title, by_full, headings):
    """按 完整条目 -> 章节号 -> 标题 -> 标题前缀 的顺序解析。"""
    k = norm(ref)
    if k in by_full:
        return by_full[k]
    if k in by_num:
        return by_num[k]  # 纯章节号，如 "5.8.1" / "第3章"（映射文件的主要写法）
    num, title, clean = split_entry(ref)
    if num and norm(num) in by_num:
        return by_num[norm(num)]
    for key in (norm(title), k):
        if key in by_title and len(by_title[key]) == 1:
            return by_title[key][0]
    # 无编号标题（如"附表2 ..."）允许前缀匹配，唯一命中才算数
    cands = [h for h in headings if not h.number and norm(h.title).startswith(k)]
    return cands[0] if len(cands) == 1 else None


def resolve_mapping(mapping: dict, headings) -> dict:
    """{评审因素: [章节号或标题]} -> {评审因素: [正文真实标题]}；解析不到就抛错。"""
    by_num, by_title, by_full = build_lookups(headings)
    out, missing = {}, []
    for factor, refs in mapping.items():
        if factor.startswith("_"):  # 允许 JSON 里放 _注释 字段
            continue
        entries = []
        for ref in refs:
            h = find_heading(ref, by_num, by_title, by_full, headings)
            if h is None:
                missing.append((factor, ref))
            else:
                entries.append(clean_title(h.display))
        out[norm(factor)] = entries
    if missing:
        raise MappingUnresolved(missing)
    return out


def extract_mapping(path, index_headers, factor_headers) -> dict:
    """从一份已填好的文件抽出 {评审因素: [章节条目]}（同项目多卷复用时用）。"""
    _, _, tbl, col, fac, _ = prepare(path, index_headers, factor_headers)
    if fac is None:
        raise XrefError("参照文件缺少「评审因素」列，无法建立映射")
    mapping = {}
    for ri, row in enumerate(tbl.findall(w("tr"))):
        if ri == 0:
            continue
        cells = row.findall(w("tc"))
        if max(col, fac) >= len(cells):
            continue
        key = cell_text(cells[fac]).strip()
        entries = [e for e in (TAIL_RE.sub("", text_of(p).strip()) for p in cells[col].findall(w("p"))) if e]
        if key and entries:
            mapping[key] = entries
    return mapping


# --------------------------------------------------------------------------
# XML 构造：书签 / 超链接 / PAGEREF 域
# --------------------------------------------------------------------------
def _copy_rpr(rpr):
    c = copy.deepcopy(rpr)
    c.tag = w("rPr")
    return c


def make_run(text, rpr):
    r = etree.Element(w("r"))
    if rpr is not None:
        r.append(_copy_rpr(rpr))
    t = etree.SubElement(r, w("t"))
    t.set(XML_SPACE, "preserve")
    t.text = text
    return r


def first_rpr(p):
    """取段落里第一处字符格式；空段落退回 pPr/rPr（段落标记的字体）。"""
    for r in p.findall(w("r")):
        if r.find(w("rPr")) is not None:
            return r.find(w("rPr"))
    for h in p.findall(w("hyperlink")):
        for r in h.findall(w("r")):
            if r.find(w("rPr")) is not None:
                return r.find(w("rPr"))
    pPr = p.find(w("pPr"))
    return pPr.find(w("rPr")) if pPr is not None else None


def make_hyperlink(anchor, text, rpr, styled=False):
    h = etree.Element(w("hyperlink"))
    h.set(w("anchor"), anchor)
    h.set(w("history"), "1")
    r = make_run(text, rpr)
    if styled:
        rpr_el = r.find(w("rPr"))
        if rpr_el is None:
            rpr_el = etree.Element(w("rPr"))
            r.insert(0, rpr_el)
        etree.SubElement(rpr_el, w("rStyle")).set(w("val"), "Hyperlink")
    h.append(r)
    return h


def make_pageref(anchor, cached, rpr):
    """{ PAGEREF anchor \\h }，带缓存结果，Word 打开即显示、F9 刷新。"""
    def fld(kind):
        r = etree.Element(w("r"))
        if rpr is not None:
            r.append(_copy_rpr(rpr))
        etree.SubElement(r, w("fldChar")).set(w("fldCharType"), kind)
        return r

    instr = etree.Element(w("r"))
    if rpr is not None:
        instr.append(_copy_rpr(rpr))
    it = etree.SubElement(instr, w("instrText"))
    it.set(XML_SPACE, "preserve")
    it.text = f" PAGEREF {anchor} \\h "
    return [fld("begin"), instr, fld("separate"), make_run(cached, rpr), fld("end")]


def existing_xref_bookmark(p):
    for b in p.findall(w("bookmarkStart")):
        if (b.get(w("name")) or "").startswith(BOOKMARK_PREFIX):
            return b.get(w("name"))
    return None


def ensure_bookmark(heading, state):
    if heading.bookmark:
        return heading.bookmark
    p = heading.el
    name = existing_xref_bookmark(p)
    if name:
        heading.bookmark = name
        return name

    state["bm_id"] += 1
    state["bm_seq"] += 1
    state["created"] += 1
    name = f"{BOOKMARK_PREFIX}{state['bm_seq']:04d}"

    bs = etree.Element(w("bookmarkStart"))
    bs.set(w("id"), str(state["bm_id"]))
    bs.set(w("name"), name)
    pPr = p.find(w("pPr"))
    p.insert((list(p).index(pPr) + 1) if pPr is not None else 0, bs)  # 必须在 pPr 之后
    be = etree.SubElement(p, w("bookmarkEnd"))
    be.set(w("id"), str(state["bm_id"]))

    heading.bookmark = name
    return name


def rebuild_paragraph(p, anchor, display, rpr, styled=False):
    for child in list(p):
        if etree.QName(child).localname not in ("pPr", "bookmarkStart", "bookmarkEnd"):
            p.remove(child)
    p.append(make_hyperlink(anchor, display, rpr, styled))
    p.append(make_run(PAGE_PREFIX, rpr))
    for el in make_pageref(anchor, PAGE_PLACEHOLDER, rpr):
        p.append(el)


def fill_cells(tbl, col, fac, mapping, overwrite):
    """按「评审因素」把章节条目写进「章节索引」单元格。"""
    filled, skipped, nokey = [], [], []
    for ri, row in enumerate(tbl.findall(w("tr"))):
        if ri == 0:
            continue
        cells = row.findall(w("tc"))
        if max(col, fac) >= len(cells):
            continue
        cell = cells[col]
        if [p for p in cell.findall(w("p")) if text_of(p).strip()] and not overwrite:
            skipped.append(ri)
            continue
        entries = mapping.get(norm(cell_text(cells[fac])))
        if not entries:
            nokey.append((ri, cell_text(cells[fac]).strip()[:40]))
            continue

        paras = cell.findall(w("p"))
        template = paras[0]
        for p in paras[1:]:
            cell.remove(p)
        for child in list(template):
            if etree.QName(child).localname != "pPr":
                template.remove(child)

        blank = copy.deepcopy(template)  # 必须在写入正文之前留干净模板，否则内容会累加
        anchor = template
        for i, e in enumerate(entries):
            p = template if i == 0 else copy.deepcopy(blank)
            if i > 0:
                anchor.addnext(p)
                anchor = p
            p.append(make_run(e, first_rpr(p)))
        filled.append((ri, len(entries)))
    return {"filled": filled, "skipped": skipped, "nokey": nokey}


def save_docx(src, dst, document_xml: bytes):
    """只换 document.xml，其余部件原样复制。"""
    tmp = dst + ".tmp"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = document_xml if item.filename == "word/document.xml" else zin.read(item.filename)
            zi = zipfile.ZipInfo(item.filename, date_time=item.date_time)
            zi.compress_type = item.compress_type
            zi.external_attr = item.external_attr
            zout.writestr(zi, data)
    shutil.move(tmp, dst)


# --------------------------------------------------------------------------
# 调 Word 更新域，把真实页码写进文件
# --------------------------------------------------------------------------
def update_fields_with_word(path: str) -> bool:
    try:
        import win32com.client as win32
    except ImportError:
        print("  ! 未安装 pywin32，跳过页码计算")
        return False

    import time
    path = os.path.abspath(path)
    word, last_err = None, None
    for _ in range(3):
        try:
            word = win32.Dispatch("Word.Application")
            break
        except Exception as e:  # 偶发"服务器运行失败"，多为残留进程占用
            last_err = e
            time.sleep(5)
    if word is None:
        print(f"  ! 无法启动 Word：{last_err}（先结束残留的 WINWORD.EXE 再重试）")
        return False

    try:
        # 这些设置可有可无，某些会话状态下赋值会被拒，不能让它们打断主流程
        for setter in (lambda: setattr(word, "Visible", False),
                       lambda: setattr(word, "DisplayAlerts", 0),
                       lambda: setattr(word, "AutomationSecurity", 3),
                       lambda: setattr(word.Options, "SaveInterval", 0)):
            try:
                setter()
            except Exception:
                pass
        doc = word.Documents.Open(path, ConfirmConversions=False, ReadOnly=False,
                                  AddToRecentFiles=False, Revert=True)
        try:
            # 顺序要紧：先 Fields.Update() 让 Word 自己完成首次分页，再 Repaginate()。
            # 反过来先强制重排，会在超大文档上死锁。
            doc.Fields.Update()
            for story in doc.StoryRanges:
                story.Fields.Update()
            doc.Repaginate()
            doc.Fields.Update()
            doc.Save()
        finally:
            doc.Close(SaveChanges=-1)
        return True
    except Exception as e:
        print(f"  ! Word 更新域失败：{e}")
        return False
    finally:
        try:
            word.Quit()
        except Exception:
            pass


# --------------------------------------------------------------------------
# 库函数：inspect / build / verify
# --------------------------------------------------------------------------
def inspect_docx(docx, index_headers=None, factor_headers=None, max_level=3, outdir=None) -> dict:
    """导出标题树与索引表原文，返回统计。"""
    index_headers = index_headers or DEFAULT_INDEX_HEADERS
    factor_headers = factor_headers or DEFAULT_FACTOR_HEADERS
    _, _, tbl, col, fac, headings = prepare(docx, index_headers, factor_headers)
    outdir = outdir or os.path.dirname(os.path.abspath(docx))
    os.makedirs(outdir, exist_ok=True)
    f_struct = os.path.join(outdir, "_结构.txt")
    f_rows = os.path.join(outdir, "_索引表.txt")

    with open(f_struct, "w", encoding="utf-8") as f:
        for h in headings:
            if h.level <= max_level:
                f.write("  " * (h.level - 1) + h.display + "\n")

    rows = tbl.findall(w("tr"))
    empty = 0
    with open(f_rows, "w", encoding="utf-8") as f:
        for ri, row in enumerate(rows):
            if ri == 0:
                continue
            cells = row.findall(w("tc"))
            factor = cell_text(cells[fac]).strip() if fac is not None and fac < len(cells) else ""
            cur = cell_text(cells[col]).strip() if col < len(cells) else ""
            if not cur:
                empty += 1
            f.write(f"===== 行{ri}  评审因素：{factor}\n")
            for ci, c in enumerate(cells):
                if ci in (fac, col):
                    continue
                t = cell_text(c).strip()
                if len(t) > 2:  # 跳过序号之类的短列
                    f.write(t + "\n")
            f.write(f"--- 现有章节索引：{cur or '（空）'}\n\n")

    return {
        "headingCount": len(headings),
        "maxLevel": max_level,
        "structureFile": f_struct,
        "rowsFile": f_rows,
        "rowCount": len(rows) - 1,
        "emptyRowCount": empty,
        "indexColumn": col,
        "factorColumn": fac,
    }


def build_xref(
    docx,
    output=None,
    *,
    mapping=None,
    index_headers=None,
    factor_headers=None,
    overwrite=False,
    sync_title=False,
    styled_link=False,
    dry_run=False,
    use_word=False,
) -> dict:
    """填列（可选）+ 建交叉引用 + 算页码，返回结构化报告。"""
    index_headers = index_headers or DEFAULT_INDEX_HEADERS
    factor_headers = factor_headers or DEFAULT_FACTOR_HEADERS
    if not os.path.isfile(docx):
        raise XrefError(f"文件不存在：{docx}")
    dst = output or re.sub(r"\.docx$", "_交叉索引.docx", docx, flags=re.I)
    if os.path.abspath(dst) == os.path.abspath(docx):
        raise XrefError("输出文件不能覆盖输入文件")

    doc, body, tbl, col, fac, headings = prepare(docx, index_headers, factor_headers)

    fill_report = None
    if mapping:
        if fac is None:
            raise XrefError("填写章节索引列需要表格里有「评审因素」列")
        resolved = resolve_mapping(mapping, headings)  # 解析不到会抛 MappingUnresolved
        fill_report = fill_cells(tbl, col, fac, resolved, overwrite)

    by_num, by_title, by_full = build_lookups(headings)
    state = {
        "bm_id": max(
            (int(b.get(w("id"))) for b in doc.iter(w("bookmarkStart")) if (b.get(w("id")) or "").isdigit()),
            default=0,
        ),
        "bm_seq": 0,
        "created": 0,
    }
    for h in headings:
        nm = existing_xref_bookmark(h.el)
        if nm:
            h.bookmark = nm
            m = re.search(r"(\d+)$", nm)
            if m:
                state["bm_seq"] = max(state["bm_seq"], int(m.group(1)))

    linked, mismatch, unresolved = [], [], []
    row_count = 0
    for ri, row in enumerate(tbl.findall(w("tr"))):
        if ri == 0:
            continue
        row_count += 1
        cells = row.findall(w("tc"))
        if col >= len(cells):
            continue
        for p in cells[col].findall(w("p")):
            raw = text_of(p).strip()
            if not raw:
                continue
            _, _, clean = split_entry(raw)
            h = find_heading(clean, by_num, by_title, by_full, headings)
            if h is None:
                unresolved.append({"row": ri, "text": clean})
                continue
            if norm(h.display) != norm(clean):
                mismatch.append({"row": ri, "indexText": clean, "headingText": h.display})
            display = clean_title(h.display) if sync_title else clean
            rebuild_paragraph(p, ensure_bookmark(h, state), display, first_rpr(p), styled_link)
            linked.append({"row": ri, "text": display})

    report = {
        "inputFile": os.path.abspath(docx),
        "outputFile": "" if dry_run else os.path.abspath(dst),
        "dryRun": bool(dry_run),
        "headingCount": len(headings),
        "rowCount": row_count,
        "entryCount": len(linked) + len(unresolved),
        "linked": linked,
        "mismatch": mismatch,
        "unresolved": unresolved,
        "bookmarksCreated": state["created"],
        "fill": fill_report,
        "pageNumbersResolved": False,
    }
    if dry_run:
        return report

    save_docx(docx, dst, etree.tostring(doc, xml_declaration=True, encoding="UTF-8", standalone=True))
    if use_word:
        report["pageNumbersResolved"] = update_fields_with_word(dst)
    return report


def verify_xref(docx, index_headers=None, factor_headers=None) -> dict:
    """校验成品：条目/超链接/PAGEREF 数、书签可解析性、与目录页码一致性、关系引用完整性。"""
    index_headers = index_headers or DEFAULT_INDEX_HEADERS
    factor_headers = factor_headers or DEFAULT_FACTOR_HEADERS
    z = zipfile.ZipFile(docx)
    bad_member = z.testzip()
    doc, body, tbl, col, fac, _ = prepare(docx, index_headers, factor_headers)

    total, zero = 0, []
    for ri, row in enumerate(tbl.findall(w("tr"))):
        if ri == 0:
            continue
        cells = row.findall(w("tc"))
        if col >= len(cells):
            continue
        for p in cells[col].findall(w("p")):
            t = text_of(p).strip()
            if not t:
                continue
            total += 1
            if re.search(r"[，,]P0$", t):
                zero.append(t)

    instr = [x.text or "" for x in tbl.iter(w("instrText"))]
    hyperlinks = len(list(tbl.iter(w("hyperlink")))) + sum(1 for i in instr if "HYPERLINK" in i)
    pagerefs = sum(1 for i in instr if "PAGEREF" in i)
    names = {b.get(w("name")) for b in doc.iter(w("bookmarkStart"))}
    refs = set(re.findall(r"PAGEREF\s+(\S+)", " ".join(instr)))

    # 与目录页码交叉比对（目录一般只含 1-2 级）
    sty = etree.fromstring(z.read("word/styles.xml"))
    tocids = set()
    for s in sty.iter(w("style")):
        nm_el = s.find(w("name"))
        nm = nm_el.get(w("val")) if nm_el is not None else ""
        if re.match(r"^toc [12]$", nm or "", re.I):
            tocids.add(s.get(w("styleId")))
    toc = {}
    for p in body.iter(w("p")):
        pPr = p.find(w("pPr"))
        st = pPr.find(w("pStyle")) if pPr is not None else None
        if st is not None and st.get(w("val")) in tocids:
            m = re.match(r"^(.*?)\s*(\d+)$", text_of(p).strip())
            if m:
                toc[norm(m.group(1))] = m.group(2)
    ours = {}
    for p in tbl.iter(w("p")):
        m = re.match(r"^(.*?)[，,]P(\d+)$", text_of(p).strip())
        if m and m.group(2) != PAGE_PLACEHOLDER:  # 占位符不参与比对，否则全是假不一致
            ours[norm(m.group(1))] = m.group(2)
    comparable = [k for k in ours if k in toc]
    conflicts = [{"title": k, "indexPage": ours[k], "tocPage": toc[k]} for k in comparable if ours[k] != toc[k]]

    # 关系引用完整性（确认没有破坏图片等资源）
    n = set(z.namelist())
    used = dangling = 0
    for part in [x for x in n if x.startswith("word/") and x.endswith(".xml")]:
        rels = "word/_rels/" + part.split("word/", 1)[1] + ".rels"
        if rels not in n:
            continue
        rmap = {q.get("Id"): q.get("Target") for q in etree.fromstring(z.read(rels))
                if q.get("TargetMode") != "External"}
        try:
            rt = etree.fromstring(z.read(part))
        except Exception:
            continue
        for el in rt.iter():
            for a in ("embed", "id", "link"):
                v = el.get(R + a)
                if v is None:
                    continue
                used += 1
                t = rmap.get(v)
                if t is None or (("word/" + t).replace("word/../", "") not in n and not t.startswith("#")):
                    dangling += 1

    return {
        "file": os.path.abspath(docx),
        "zipCorruptMember": bad_member or "",
        "entryCount": total,
        "hyperlinkCount": hyperlinks,
        "pagerefCount": pagerefs,
        "bookmarksResolvable": refs <= names,
        "missingBookmarks": sorted(refs - names),
        "unresolvedPageCount": len(zero),
        "tocComparableCount": len(comparable),
        "tocConflicts": conflicts,
        "relationshipCount": used,
        "danglingRelationshipCount": dangling,
        "mediaCount": len([x for x in n if x.startswith("word/media/")]),
        "fileSizeMb": round(os.path.getsize(docx) / 1048576, 1),
    }


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------
def cmd_inspect(args):
    r = inspect_docx(args.docx, args.index_header, args.factor_header, args.max_level, args.outdir)
    print(f"标题总数 {r['headingCount']}（导出至 {r['maxLevel']} 级）-> {r['structureFile']}")
    print(f"索引表 {r['rowCount']} 行，其中章节索引列为空的 {r['emptyRowCount']} 行 -> {r['rowsFile']}")
    print(f"章节索引列号={r['indexColumn']} 评审因素列号={r['factorColumn']}")
    if r["emptyRowCount"]:
        print("\n=> 该列需要先判断章节。读上面两个文件，按 SKILL.md 的判断方法编写映射 JSON。")
    else:
        print("\n=> 该列已填写，可直接 build 建立交叉引用。")


def cmd_build(args):
    raw_mapping = None
    if args.from_reference:
        raw_mapping = extract_mapping(args.from_reference, args.index_header, args.factor_header)
        print(f"从参照文件取得 {len(raw_mapping)} 条映射")
    elif args.mapping:
        with open(args.mapping, encoding="utf-8") as f:
            raw_mapping = json.load(f)
        print(f"载入映射 {args.mapping}")

    if args.dump_mapping:
        m = raw_mapping or extract_mapping(args.docx, args.index_header, args.factor_header)
        with open(args.dump_mapping, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
        print(f"映射已导出：{args.dump_mapping}（{len(m)} 条）")
        return

    r = build_xref(
        args.docx,
        args.output,
        mapping=raw_mapping,
        index_headers=args.index_header,
        factor_headers=args.factor_header,
        overwrite=args.overwrite,
        sync_title=args.sync_title,
        styled_link=args.styled_link,
        dry_run=args.dry_run,
        use_word=not args.no_word,
    )

    if r["fill"]:
        fr = r["fill"]
        print(f"\n已填写 {len(fr['filled'])} 行，共 {sum(n for _, n in fr['filled'])} 条")
        if fr["skipped"]:
            print(f"  跳过（已有内容）行 {fr['skipped']}，如需覆盖加 --overwrite")
        for ri, k in fr["nokey"]:
            print(f"  ! 映射里没有对应评审因素：行{ri} {k}")

    print(f"\n建立交叉引用 {len(r['linked'])} 条")
    for item in r["linked"]:
        print(f"   行{item['row']:>3}  {item['text']}")
    if r["mismatch"]:
        print(f"\n文字与正文标题不一致 {len(r['mismatch'])} 条（已按编号链接，建议核对）：")
        for item in r["mismatch"]:
            print(f"   行{item['row']:>3}  索引表:{item['indexText']}   正文:{item['headingText']}")
    if r["unresolved"]:
        print(f"\n未能匹配 {len(r['unresolved'])} 条（保持原样，需人工处理）：")
        for item in r["unresolved"]:
            print(f"   行{item['row']:>3}  {item['text']}")

    if r["dryRun"]:
        print("\n[dry-run] 未写出文件。")
        return
    print(f"\n写出 {r['outputFile']} ...")
    if args.no_word:
        print("已跳过页码计算：请在 Word 中打开，Ctrl+A 后按 F9。")
    elif r["pageNumbersResolved"]:
        print("页码已写入。")
    else:
        print("页码未算出：请在 Word 中打开，Ctrl+A 后按 F9。")
    print(f"完成：{r['outputFile']}")


def cmd_verify(args):
    r = verify_xref(args.docx, args.index_header, args.factor_header)
    print("压缩包校验:", r["zipCorruptMember"] or "通过")
    print(f"条目={r['entryCount']}  超链接={r['hyperlinkCount']}  PAGEREF域={r['pagerefCount']}")
    print("书签全部可解析:", r["bookmarksResolvable"], "| 缺失:", r["missingBookmarks"] or "无")
    print(
        f"页码未算出的条目: {r['unresolvedPageCount']}"
        + ("（在 Word 中 Ctrl+A 按 F9 即可）" if r["unresolvedPageCount"] else "")
    )
    if not r["tocComparableCount"]:
        print("与目录比对: 跳过（页码尚未计算或目录无可比条目）")
    else:
        print(f"与目录比对: 可比 {r['tocComparableCount']} 条, 不一致 {len(r['tocConflicts'])} 条")
        for c in r["tocConflicts"]:
            print(f"   {c['title']}: 索引表P{c['indexPage']} / 目录P{c['tocPage']}")
    print(
        f"关系引用={r['relationshipCount']} 失效={r['danglingRelationshipCount']}"
        f" | 图片={r['mediaCount']} | 大小={r['fileSizeMb']}MB"
    )


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="技术标评分索引表交叉引用工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("docx")
        p.add_argument("--index-header", nargs="+", default=DEFAULT_INDEX_HEADERS,
                       help="「章节索引」列的表头措辞（可多个）")
        p.add_argument("--factor-header", nargs="+", default=DEFAULT_FACTOR_HEADERS,
                       help="「评审因素」列的表头措辞（可多个）")

    p1 = sub.add_parser("inspect", help="导出标题结构与索引表原文")
    common(p1)
    p1.add_argument("--max-level", type=int, default=3, help="导出标题的最大层级，默认3")
    p1.add_argument("--outdir", help="输出目录，默认与 docx 同目录")

    p2 = sub.add_parser("build", help="填列 + 建交叉引用 + 算页码")
    common(p2)
    p2.add_argument("-o", "--output")
    p2.add_argument("--mapping", help="章节映射 JSON：{评审因素: [章节号或标题]}")
    p2.add_argument("--from-reference", help="从已填好的同结构文件套用映射")
    p2.add_argument("--dump-mapping", help="导出映射为 JSON 后退出")
    p2.add_argument("--dry-run", action="store_true")
    p2.add_argument("--no-word", action="store_true", help="不调 Word 算页码")
    p2.add_argument("--overwrite", action="store_true", help="单元格已有内容也覆盖")
    p2.add_argument("--sync-title", action="store_true", help="用正文真实标题覆盖表中文字")
    p2.add_argument("--styled-link", action="store_true", help="超链接用蓝色下划线样式")

    p3 = sub.add_parser("verify", help="校验成品")
    common(p3)

    args = ap.parse_args()
    try:
        {"inspect": cmd_inspect, "build": cmd_build, "verify": cmd_verify}[args.cmd](args)
    except XrefError as exc:
        raise SystemExit(str(exc))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    main()
