# -*- coding: utf-8 -*-
"""技术标正文图表题注自动编号。

表注在表格上方居中（`表1-1`），图注在图片下方居中（`图1-1`），编号按章走、每章从 1 重计。

移植自通用题注工具 `add_captions.py`（在 190MB / 179 表 / 约 800 图的真实技术卷上跑通）。
与通用版的差异都是为了适配本项目方案 B：

1. **章号来自 Heading 1 文本**，不是数 Heading 1 的个数。方案 B 把章节号写死在标题文本里
   （"第一章  标前概述"），而正文里还有"目录""前言"这两个无编号 Heading 1，纯计数会整体
   错位。因此从 H1 文本正则抽 `第X章` 并把中文数字转成阿拉伯数字；抽不到的 H1（目录/前言）
   把当前章号置 0，其下的图表不编号。
   整篇都抽不到章号时退回按 H1 顺序计数，并报 `caption_chapter_fallback` warning。
2. **不用 STYLEREF 域取章号**。方案 B 已剥掉所有 `w:numPr`，`{ STYLEREF 1 \\s }` 取回来的是
   整句标题而不是章号，只能写固定文字。
3. **题注段样式取 `heading_style.json` 的 `caption` 段**，与格式清洗/自定义格式切换同一份契约。

SEQ 计数器名必须等于可见前缀（`图`/`表`），否则 Word 的「引用→交叉引用」对话框里一条都列不出来。
`\\s 1` 让计数器在每个一级标题处归零，所以各章都从 1 开始。

在 S4 链路里跑在正文组装之后、格式清洗之前（顺序理由见 `opencode/skills/STAGES.md`）。
纯规则脚本、不经 agent，所以不做成 skill；单独处理一份 docx 用：

    python -m app.document_processing.technical_document.captioning <manifest.json>

已知限制：

- **正文交叉引用不会自动更新**。文中"见图3-5"这类是手打的死文本，编号变了不会跟着变。
  要彻底解决得给每条题注加书签、把引用改写成 REF 域（未实现）。
- **章号是死文字**。本项目每次 S4 都从头重排整篇，不受影响；单独对已成稿文件增删整章后需重跑。
- 只处理正文 body 顶层。页眉页脚、文本框内部、真表格单元格里的图片不编号（后者是表格内容，
  本来就不该单独编号）。
- 大文件（百 MB 级）读+写耗时以分钟计、内存峰值较高，是 python-docx 全量载入所致。
"""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.text.paragraph import Paragraph
from docx.text.run import Run


DEFAULT_CONFIG: dict[str, Any] = {
    # ---- 编号文案 ----
    "table_prefix": "表",
    "figure_prefix": "图",
    "number_sep": "-",
    "title_gap": " ",

    # ---- 编号形式 ----
    # True = 章内序号写成 Word 的 SEQ 域（"表1-"是文字，"1"是域），Ctrl+A + F9 自动顺延，
    #        且能被「引用→交叉引用」列出来；False = 纯文本编号，增删后会断号。
    "use_word_fields": True,
    "seq_name_figure": "图",
    "seq_name_table": "表",
    "seq_reset_level": 1,
    "update_fields_on_open": True,

    # ---- 章节识别 ----
    "chapter_styles": ["Heading 1", "标题 1", "heading 1"],
    # 第一章之前的内容（封面、投标说明函、目录）不编号
    "prechapter_mode": "skip",

    # ---- 题注识别（判断上/下方那句话是不是"标题"）----
    "max_caption_len": 45,
    "caption_lookaround": 3,
    "sentence_enders": "。！？；;：:，,、.",
    "body_lead_words": ["如下", "下表", "下图", "见下", "以下", "上表", "上图",
                        "如上", "详见", "参见", "注：", "备注"],
    "body_lead_regex": (r"^\s*(?:[（(]\s*[\d一二三四五六七八九十]+\s*[)）]"
                        r"|\d+\s*[、.．]"
                        r"|[一二三四五六七八九十百]+\s*[、.．]"
                        r"|第\s*[一二三四五六七八九十百\d]+\s*[章节条部分讲篇])"),
    "caption_styles": ["图表标题", "题注", "Caption", "caption", "图表题注", "表标题", "图标题"],
    # 精确匹配，避免误伤"图表标题"这类含"标题"二字的题注样式
    "heading_style_patterns": [r"^heading\s*\d+$", r"^标题\s*\d+$", r"^title$",
                               r"^subtitle$", r"^副标题$", r"^toc\s*\d*$",
                               r"^toc heading$", r"^目录.*$", r"^大纲.*$"],

    # ---- 新建题注段落的样式 ----
    "new_caption_style_name": "图表题注(自动)",
    "new_caption_font": {"eastasia": "等线", "ascii": "等线", "size_pt": 12.0},
    "caption_line_spacing": 1.5,
    "force_center": True,
    # 改写已有标题时是否也套题注样式。格式清洗把题注段划为"保留段"不再刷格式，这里不统一
    # 就没有第二次机会，成稿里各素材自带的题注字体会参差不齐。
    "unify_caption_format": True,

    # ---- 图片识别 ----
    "min_image_width_cm": 3.0,
    "min_image_height_cm": 2.0,
    "skip_floating_images": True,
    "max_text_with_image": 12,
    "group_consecutive_image_paras": True,
    "split_multi_image_para": False,
    "split_width_factor": 1.15,

    # ---- 表格识别 ----
    "layout_table_as_figure": False,
    "layout_img_cell_ratio": 0.5,
    "layout_max_text_per_cell": 60,
    "skip_single_cell_table": True,

    # ---- 复核标记 ----
    # 交付稿默认不打黄标；需要人工复核卡点时由 manifest 打开
    "highlight": False,
}

# 旧编号剥离："表2-1"、"图3-2-1"、"表 11"、"图13"、"表 "、"表1."、"Table 1-1"
OLD_LABEL_RE = re.compile(
    r"^\s*(?:[图表]|[Ff]ig(?:ure)?|[Tt]ab(?:le)?)"
    r"(?:\s*\d+(?:\s*[-－—.·]\s*\d+)*\s*[.、:：]?|\s+)\s*"
)

# 方案 B 的一级标题文本形如"第一章  标前概述"/"第 1 章 xxx"
CHAPTER_TEXT_RE = re.compile(r"^\s*第\s*([0-9〇零一二三四五六七八九十百]+)\s*章")

_CN_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def chinese_number_to_int(value: str) -> int | None:
    """把"一/十二/二十三"这类中文数字转成整数；阿拉伯数字原样解析。"""
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if any(ch not in _CN_DIGITS and ch != "十" and ch != "百" for ch in text):
        return None
    total = 0
    current = 0
    for ch in text:
        if ch == "十":
            current = (current or 1) * 10
        elif ch == "百":
            current = (current or 1) * 100
        else:
            digit = _CN_DIGITS[ch]
            if current and current % 10 == 0:
                current += digit
            else:
                current = current * 10 + digit
    total += current
    return total or None


class CaptionNumberer:
    """一次编号任务。配置随实例走，不用模块级可变状态。"""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config: dict[str, Any] = dict(DEFAULT_CONFIG)
        if config:
            self.config.update({key: value for key, value in config.items() if value is not None})
        self.warnings: list[dict[str, Any]] = []

    # ---------------- 基础工具 ----------------
    @staticmethod
    def el_text(el) -> str:
        """深度取文：`paragraph.text` 读不到 `w:fldSimple` 里的内容，域模式下会漏掉编号数字。"""
        return "".join(node.text or "" for node in el.iter(qn("w:t")))

    @staticmethod
    def style_name_of(paragraph: Paragraph) -> str:
        try:
            return paragraph.style.name or ""
        except Exception:
            return ""

    def is_heading_style(self, name: str) -> bool:
        low = (name or "").strip().lower()
        if not low:
            return False
        return any(re.match(pattern, low) for pattern in self.config["heading_style_patterns"])

    def is_chapter_para(self, paragraph: Paragraph) -> bool:
        return self.style_name_of(paragraph) in self.config["chapter_styles"]

    @staticmethod
    def iter_images(el) -> tuple[int, int, int, list[tuple[float, float]]]:
        """返回 (inline 图数, 浮动图数, VML 图数, [(宽cm, 高cm), ...])。"""
        inline = el.findall(".//" + qn("wp:inline"))
        anchor = el.findall(".//" + qn("wp:anchor"))
        pict = el.findall(".//" + qn("w:pict"))
        sizes: list[tuple[float, float]] = []
        for node in inline + anchor:
            ext = node.find(qn("wp:extent"))
            if ext is None:
                continue
            try:
                sizes.append((int(ext.get("cx")) / 360000.0, int(ext.get("cy")) / 360000.0))
            except (TypeError, ValueError):
                continue
        return len(inline), len(anchor), len(pict), sizes

    def para_has_countable_image(self, p_el) -> bool:
        """这个段落是不是"该编号的插图段落"。跳过浮动图（印章签名）、小图标、正文配图。"""
        n_inline, n_anchor, n_pict, sizes = self.iter_images(p_el)
        if n_inline + n_anchor + n_pict == 0:
            return False
        if self.config["skip_floating_images"] and n_inline == 0 and n_pict == 0 and n_anchor > 0:
            return False
        if len(self.el_text(p_el).strip()) > self.config["max_text_with_image"]:
            return False
        if sizes:
            big = [
                size for size in sizes
                if size[0] >= self.config["min_image_width_cm"] and size[1] >= self.config["min_image_height_cm"]
            ]
            if not big:
                return False
        return True

    def classify_table(self, tbl_el) -> str:
        """`data`（真表格）/ `layout`（图片排版壳）/ `skip`。

        只看"有没有图"会把每行一张照片的路况勘察表误判成排版壳，所以含图单元格占比和
        平均每格文字数必须同时命中才算伪表格。
        """
        rows = tbl_el.findall(qn("w:tr"))
        cells = []
        for row in rows:
            cells.extend(row.findall(qn("w:tc")))
        n_cells = len(cells)
        if n_cells == 0:
            return "skip"
        if n_cells == 1 and self.config["skip_single_cell_table"]:
            return "skip"

        img_cells = 0
        for cell in cells:
            n_inline, n_anchor, n_pict, _ = self.iter_images(cell)
            if n_inline + n_anchor + n_pict > 0:
                img_cells += 1
        if img_cells == 0:
            return "data"

        text_len = len(self.el_text(tbl_el).strip())
        ratio = img_cells / float(n_cells)
        per_cell = text_len / float(n_cells)
        if ratio >= self.config["layout_img_cell_ratio"] and per_cell < self.config["layout_max_text_per_cell"]:
            return "layout"
        return "data"

    @staticmethod
    def has_any_image(el) -> bool:
        return (el.find(".//" + qn("w:drawing")) is not None
                or el.find(".//" + qn("w:pict")) is not None)

    def looks_like_caption(self, paragraph: Paragraph) -> bool:
        """这个段落像不像图/表的标题。

        多图共用的一行图注常用大量空格分隔（"A试验台   B平台   C装置"），先把连续空白压成
        一个再量长度，否则会因空格超长被误判成正文。
        """
        text = re.sub(r"[\s　]+", " ", self.el_text(paragraph._p)).strip()
        if not text:
            return False
        if self.para_has_countable_image(paragraph._p):
            return False
        name = self.style_name_of(paragraph)
        if self.is_heading_style(name):
            return False
        if name in self.config["caption_styles"] or name == self.config["new_caption_style_name"]:
            return True
        if len(text) > self.config["max_caption_len"]:
            return False
        if text[-1] in self.config["sentence_enders"]:
            return False
        if "。" in text:
            return False
        for word in self.config["body_lead_words"]:
            if text.startswith(word):
                return False
        if self.config["body_lead_regex"] and re.match(self.config["body_lead_regex"], text):
            return False
        return True

    def strip_old_label(self, text: str) -> str:
        result = str(text or "").strip()
        previous = None
        while previous != result:
            previous = result
            result = OLD_LABEL_RE.sub("", result, count=1).strip()
        return result

    # ---------------- 题注写入 ----------------
    def label_head(self, kind: str, chapter: int) -> str:
        prefix = self.config["table_prefix"] if kind == "table" else self.config["figure_prefix"]
        return f"{prefix}{chapter}{self.config['number_sep']}"

    def label_text(self, kind: str, chapter: int, number: int) -> str:
        return f"{self.label_head(kind, chapter)}{number}"

    def seq_name(self, kind: str) -> str:
        return self.config["seq_name_table"] if kind == "table" else self.config["seq_name_figure"]

    @staticmethod
    def _new_run(text: str, rPr):
        run = OxmlElement("w:r")
        if rPr is not None:
            run.append(deepcopy(rPr))
        node = OxmlElement("w:t")
        node.set(qn("xml:space"), "preserve")
        node.text = text
        run.append(node)
        return run

    def _new_seq_field(self, seq_name: str, cached: int, rPr):
        """`{ SEQ 图 \\* ARABIC \\s 1 }`——与 Word 原生题注完全同构的域。

        域内写入当前值作为缓存，未按 F9 时显示也是对的，直接导 PDF 不会空白。
        """
        instr = f" SEQ {seq_name} \\* ARABIC "
        if self.config["seq_reset_level"]:
            instr += f"\\s {self.config['seq_reset_level']} "
        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), instr)
        field.append(self._new_run(str(cached), rPr))
        return field

    def enable_update_fields_on_open(self, doc) -> bool:
        """让 Word 打开文档时自动更新全部域（含题注编号与目录）。"""
        if not self.config["update_fields_on_open"]:
            return False
        settings = doc.settings.element
        for node in settings.findall(qn("w:updateFields")):
            node.set(qn("w:val"), "true")
            return True
        node = OxmlElement("w:updateFields")
        node.set(qn("w:val"), "true")
        # updateFields 在 schema 里排在 compat/rsids 等之前，插到第一个后置元素之前
        for tail in ("w:hdrShapeDefaults", "w:footnotePr", "w:endnotePr", "w:compat",
                     "w:docVars", "w:rsids", "w:themeFontLang", "w:clrSchemeMapping"):
            ref = settings.find(qn(tail))
            if ref is not None:
                ref.addprevious(node)
                return True
        settings.append(node)
        return True

    def _resolve_caption_style(self, doc):
        """优先复用文档已有的题注样式，都没有才新建；无论哪种都按 caption 规范刷一遍格式。"""
        existing: dict[str, Any] = {}
        for style in doc.styles:
            try:
                if style.type == WD_STYLE_TYPE.PARAGRAPH:
                    existing[style.name] = style
            except Exception:
                continue

        style = None
        for name in [*self.config["caption_styles"], self.config["new_caption_style_name"]]:
            if name in existing:
                style = existing[name]
                break
        if style is None:
            style = doc.styles.add_style(self.config["new_caption_style_name"], WD_STYLE_TYPE.PARAGRAPH)
            try:
                style.base_style = doc.styles["Normal"]
            except Exception:
                pass

        font_cfg = self.config["new_caption_font"]
        style.font.name = font_cfg["ascii"]
        style.font.size = Pt(font_cfg["size_pt"])
        rPr = style.element.get_or_add_rPr()
        rPr.get_or_add_rFonts().set(qn("w:eastAsia"), font_cfg["eastasia"])
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        line_spacing = self.config.get("caption_line_spacing")
        if line_spacing:
            style.paragraph_format.line_spacing = float(line_spacing)
        return style

    def _mark(self, paragraph: Paragraph) -> None:
        """给题注涂黄。域里的 run 也要涂到，`paragraph.runs` 拿不到域内部的 run。"""
        if not self.config["highlight"]:
            return
        for r_el in paragraph._p.iter(qn("w:r")):
            Run(r_el, paragraph).font.highlight_color = WD_COLOR_INDEX.YELLOW

    def _write_content(self, paragraph: Paragraph, kind: str, chapter: int, number: int, title: str, rPr) -> None:
        p_el = paragraph._p
        for child in list(p_el):
            if child.tag != qn("w:pPr"):
                p_el.remove(child)
        tail = (self.config["title_gap"] + title) if title else ""
        if self.config["use_word_fields"]:
            p_el.append(self._new_run(self.label_head(kind, chapter), rPr))
            p_el.append(self._new_seq_field(self.seq_name(kind), number, rPr))
            if tail:
                p_el.append(self._new_run(tail, rPr))
        else:
            p_el.append(self._new_run(self.label_text(kind, chapter, number) + tail, rPr))

    def _fill_new(self, doc, style, p_el, kind: str, chapter: int, number: int) -> Paragraph:
        paragraph = Paragraph(p_el, doc._body)
        try:
            paragraph.style = style
        except Exception:
            pass
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self._write_content(paragraph, kind, chapter, number, "", None)
        self._mark(paragraph)
        return paragraph

    def _relabel(self, paragraph: Paragraph, style, kind: str, chapter: int, number: int) -> str:
        """在已有标题前加编号（先剥离旧编号）。

        `unify_caption_format` 打开时套题注样式并丢掉原有直接格式（直接格式会盖过样式，
        不丢就统一不了）；关闭时沿用原有字体，只补编号和居中。
        """
        title = self.strip_old_label(self.el_text(paragraph._p))
        rPr = None
        if self.config["unify_caption_format"]:
            try:
                paragraph.style = style
            except Exception:
                pass
        else:
            first_run = paragraph._p.find(".//" + qn("w:r"))
            if first_run is not None:
                found = first_run.find(qn("w:rPr"))
                if found is not None:
                    rPr = deepcopy(found)
                    for highlight in rPr.findall(qn("w:highlight")):
                        rPr.remove(highlight)  # 旧底纹不带进来，由 _mark 统一控制
        self._write_content(paragraph, kind, chapter, number, title, rPr)
        if self.config["force_center"]:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self._mark(paragraph)
        return title

    # ---------------- 章号 ----------------
    def chapter_no_from_heading(self, paragraph: Paragraph) -> int | None:
        """从"第一章  标前概述"抽出章号。抽不到（目录/前言）返回 None。"""
        match = CHAPTER_TEXT_RE.match(re.sub(r"[\s　]+", " ", self.el_text(paragraph._p)).strip())
        if not match:
            return None
        return chinese_number_to_int(match.group(1))

    def _chapter_mode(self, doc) -> str:
        """整篇 H1 里能抽到章号就按文本走，一个都抽不到才退回按顺序计数。"""
        heading_count = 0
        numbered = 0
        for el in doc.element.body.iterchildren(qn("w:p")):
            paragraph = Paragraph(el, doc._body)
            if not self.is_chapter_para(paragraph):
                continue
            heading_count += 1
            if self.chapter_no_from_heading(paragraph) is not None:
                numbered += 1
        if heading_count and not numbered:
            self.warnings.append({
                "code": "caption_chapter_fallback",
                "message": f"{heading_count} 个一级标题都没有「第X章」文本编号，章号退回按标题顺序计数，请核对图表编号的章号。",
                "count": heading_count,
            })
            return "count"
        return "heading_text"

    # ---------------- 主流程 ----------------
    def _next_nonempty_is_table(self, children, index: int, parent) -> bool:
        cursor = index + 1
        while cursor < len(children):
            el = children[cursor]
            if el.tag.endswith("}tbl"):
                return True
            if not el.tag.endswith("}p"):
                return False
            if Paragraph(el, parent).text.strip() or self.para_has_countable_image(el):
                return False
            cursor += 1
        return False

    def _find_existing_caption(self, children, index: int, direction: int, used: set[int], parent):
        """从 index 出发向 direction(±1) 找已有题注段落，跨过空段落。"""
        steps = 0
        cursor = index + direction
        while 0 <= cursor < len(children) and steps <= self.config["caption_lookaround"]:
            el = children[cursor]
            if not el.tag.endswith("}p"):
                break
            if cursor in used:
                break
            paragraph = Paragraph(el, parent)
            if not self.el_text(el).strip():
                # 空段落可以跨过去找题注，但"只有图没有字"的段落不行——那是另一张图，
                # 它下面的题注属于它，不能被上一张图抢走
                if self.has_any_image(el):
                    return (None, None)
                cursor += direction
                steps += 1
                continue
            if not self.looks_like_caption(paragraph):
                return (None, None)
            # 图注向下找候选时，若该段紧跟着一个表格，让给表格——夹在图和表之间的
            # 标题（"制造基地产能总表"）属于表
            if direction > 0 and self._next_nonempty_is_table(children, cursor, parent):
                return (None, None)
            return (cursor, paragraph)
        return (None, None)

    def process(self, doc) -> list[dict[str, Any]]:
        """给整篇 docx 加题注，返回处理记录。"""
        chapter_mode = self._chapter_mode(doc)
        body = doc.element.body
        children = list(body.iterchildren())  # 遍历前的快照，插入一律延后到循环结束
        parent = doc._body
        style = self._resolve_caption_style(doc)

        chapter = 0
        tbl_no = 0
        fig_no = 0
        used: set[int] = set()
        records: list[dict[str, Any]] = []
        pending: list[tuple[Any, str, int, int, int]] = []

        prechapter_skip = self.config["prechapter_mode"] == "skip"
        skip_until = -1

        for idx, el in enumerate(children):
            if idx <= skip_until:
                continue
            tag = el.tag.split("}")[-1]

            if tag == "p":
                paragraph = Paragraph(el, parent)
                if self.is_chapter_para(paragraph):
                    if chapter_mode == "count":
                        chapter += 1
                    else:
                        # 目录/前言这类无编号 H1 把章号归零，其下内容不编号
                        chapter = self.chapter_no_from_heading(paragraph) or 0
                    tbl_no = 0
                    fig_no = 0
                    continue

            if chapter == 0 and prechapter_skip:
                continue

            target = el
            anchor_idx = idx

            if tag == "tbl":
                classification = self.classify_table(el)
                if classification == "skip":
                    continue
                if classification == "data":
                    kind = "table"
                elif self.config["layout_table_as_figure"]:
                    kind = "figure"
                else:
                    continue
                source = "表格" if classification == "data" else "伪表格(图片排版)"
            elif tag == "p":
                if not self.para_has_countable_image(el):
                    continue
                # 紧挨着的纯图片段落归为同一张图，题注挂在整组最后一张图下方
                end = idx
                if self.config["group_consecutive_image_paras"]:
                    while (end + 1 < len(children)
                           and children[end + 1].tag.endswith("}p")
                           and self.para_has_countable_image(children[end + 1])):
                        end += 1
                skip_until = end
                target = children[end]
                anchor_idx = end
                kind = "figure"
                source = "图片段落" if end == idx else f"图片段落(合并{end - idx + 1}段)"
            else:
                continue

            if kind == "table":
                tbl_no += 1
                number = tbl_no
                direction = -1  # 表注在上方
            else:
                fig_no += 1
                number = fig_no
                direction = +1  # 图注在下方

            cap_idx, cap_para = self._find_existing_caption(children, anchor_idx, direction, used, parent)
            if cap_para is not None:
                used.add(cap_idx)
                title = self._relabel(cap_para, style, kind, chapter, number)
                action = "改写已有标题"
            else:
                title = ""
                action = "新插入题注"
                pending.append((target, kind, chapter, number, direction))

            records.append({
                "chapter": chapter,
                "label": self.label_text(kind, chapter, number),
                "kind": kind,
                "source": source,
                "action": action,
                "title": title,
                "index": idx,
            })

        # 统一执行插入（倒序，避免相邻元素互相干扰）
        for target, kind, chapter_no, number, direction in reversed(pending):
            p_el = OxmlElement("w:p")
            if direction < 0:
                target.addprevious(p_el)
            else:
                target.addnext(p_el)
            self._fill_new(doc, style, p_el, kind, chapter_no, number)

        if self.config["use_word_fields"]:
            self.enable_update_fields_on_open(doc)
        return records


def verify_numbered_docx(doc, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """交接说明第 7 节的两条硬校验，结果转成结构化 warning。

    - 位置校验：每条表注向下跨过空段后必须紧跟 `w:tbl`；
    - 连号校验：按章分组，图/表序号必须是 1..N 连续。
    """
    numberer = CaptionNumberer(config)
    prefix_pattern = (re.escape(numberer.config["table_prefix"]) + "|"
                      + re.escape(numberer.config["figure_prefix"]))
    label_re = re.compile(rf"^\s*({prefix_pattern})\s*(\d+){re.escape(numberer.config['number_sep'])}(\d+)(?:\s|$|[^\d])")

    parent = doc._body
    children = list(doc.element.body.iterchildren())
    seen: dict[tuple[str, int], list[int]] = {}
    misplaced = 0

    for idx, el in enumerate(children):
        if not el.tag.endswith("}p"):
            continue
        match = label_re.match(numberer.el_text(el).strip())
        if not match:
            continue
        prefix, chapter_text, number_text = match.group(1), match.group(2), match.group(3)
        kind = "table" if prefix == numberer.config["table_prefix"] else "figure"
        seen.setdefault((kind, int(chapter_text)), []).append(int(number_text))
        if kind == "table" and not numberer._next_nonempty_is_table(children, idx, parent):
            misplaced += 1

    broken: list[str] = []
    for (kind, chapter_no), numbers in seen.items():
        if numbers == list(range(1, len(numbers) + 1)):
            continue
        prefix = numberer.config["table_prefix"] if kind == "table" else numberer.config["figure_prefix"]
        broken.append(f"{prefix}{chapter_no}{numberer.config['number_sep']}{numbers[0]}")

    warnings: list[dict[str, Any]] = []
    if misplaced:
        warnings.append({
            "code": "caption_table_position",
            "message": f"{misplaced} 条表注下方没有紧跟表格，可能挂错了对象，请人工抽检。",
            "count": misplaced,
        })
    if broken:
        # 常见成因：素材自带的手写编号在图片上方，本工具的图注只向下认，改写不到它
        sample = "、".join(sorted(broken)[:5])
        warnings.append({
            "code": "caption_number_gap",
            "message": f"{len(broken)} 组图表编号在章内不连续（如 {sample}），多为素材自带的手写编号未被改写，请人工核对。",
            "count": len(broken),
        })
    return warnings


def number_captions(
    input_file: str | Path,
    output_file: str | Path,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """读入 docx，加图表题注，另存到 output_file。不改输入文件。"""
    input_path = Path(input_file)
    output_path = Path(output_file)
    if input_path.resolve() == output_path.resolve():
        raise ValueError("图表题注编号的输出文件不能与输入文件相同。")
    if not input_path.exists():
        raise FileNotFoundError(f"图表题注编号找不到输入文件：{input_path}")

    numberer = CaptionNumberer(config)
    doc = Document(str(input_path))
    records = numberer.process(doc)
    verify_warnings = verify_numbered_docx(doc, config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))

    table_count = sum(1 for record in records if record["kind"] == "table")
    figure_count = sum(1 for record in records if record["kind"] == "figure")
    inserted_count = sum(1 for record in records if record["action"] == "新插入题注")
    chapters = {record["chapter"] for record in records}
    return {
        "records": records,
        "summary": {
            "captionCount": len(records),
            "tableCount": table_count,
            "figureCount": figure_count,
            "insertedCount": inserted_count,
            "relabeledCount": len(records) - inserted_count,
            "chapterCount": len(chapters),
            "numberingMode": "seq_field" if numberer.config["use_word_fields"] else "plain",
            "highlighted": bool(numberer.config["highlight"]),
        },
        "warnings": [*numberer.warnings, *verify_warnings],
    }
