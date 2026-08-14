"""段落样式的预建索引：一次解析 styles.xml，替代逐段落的 python-docx 样式解析。

python-docx 的 `paragraph.style` 每次访问都要按关系表定位 styles 部件、线性扫描
全部样式定义，找不到还要再扫一遍取默认样式。清洗/编号阶段对几万个段落逐个问
"你是不是标题/目录样式"，这条路径就被走了上千万次——实测 2MB 轻量稿的格式清洗
里，底层取关系类型的函数被调用 1.7 亿次，占了全阶段绝大部分耗时。

样式定义在一次处理循环内不会变化，所以按 styles 元素建一次索引、后续全部查表。
索引按文档部件弱引用缓存，并用 styles 元素的子节点数做指纹：合并（docxcompose
往母版增补样式）或裁剪（prune_unused_styles）改变样式集合后自动重建。

语义对齐 python-docx 的关键点：
- 段落无 pStyle 或指向不存在的样式 id 时，回落到默认段落样式（get_by_id 同款行为）。
- 样式名做 BabelFish 翻译（"heading 1" → "Heading 1"），与 `Style.name` 一致。
- basedOn 链带 visited 保护，断链（指向不存在的 id）即终止，与 `base_style` 一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from weakref import WeakKeyDictionary

from docx.oxml.ns import qn
from docx.styles.style import BabelFish


@dataclass(frozen=True)
class StyleEntry:
    style_id: str
    name: str  # UI 名（已做 BabelFish 翻译），与 python-docx Style.name 一致
    outline_level: int | None  # 样式 pPr 里的 w:outlineLvl 换算的 1-9 级，无则 None
    based_on: str | None


class StyleIndex:
    """一个 styles.xml 的查表视图。只读；样式集合变化后由缓存层重建。"""

    def __init__(self, styles_element) -> None:
        self._entries: dict[str, StyleEntry] = {}
        self._default_id: str | None = None
        for style_el in styles_element.findall(qn("w:style")):
            if style_el.get(qn("w:type")) != "paragraph":
                continue
            style_id = style_el.get(qn("w:styleId")) or ""
            name_el = style_el.find(qn("w:name"))
            raw_name = (name_el.get(qn("w:val")) if name_el is not None else None) or ""
            outline_level = None
            based_on = None
            p_pr = style_el.find(qn("w:pPr"))
            if p_pr is not None:
                outline_el = p_pr.find(qn("w:outlineLvl"))
                if outline_el is not None:
                    try:
                        value = int(outline_el.get(qn("w:val")))
                    except (TypeError, ValueError):
                        value = -1
                    if 0 <= value <= 8:
                        outline_level = value + 1
            based_on_el = style_el.find(qn("w:basedOn"))
            if based_on_el is not None:
                based_on = based_on_el.get(qn("w:val")) or None
            self._entries[style_id] = StyleEntry(
                style_id=style_id,
                name=BabelFish.internal2ui(raw_name) if raw_name else "",
                outline_level=outline_level,
                based_on=based_on,
            )
            # python-docx 的 default_for 取最后一个 default 样式（[-1]），这里保持一致
            if style_el.get(qn("w:default")) in {"1", "true", "on"}:
                self._default_id = style_id

    @staticmethod
    def raw_style_id(para) -> str | None:
        """段落 pPr/pStyle 里写的原始样式 id；没写返回 None。纯元素访问，不触发样式解析。"""
        p_pr = para._p.find(qn("w:pPr"))
        if p_pr is None:
            return None
        p_style = p_pr.find(qn("w:pStyle"))
        if p_style is None:
            return None
        return p_style.get(qn("w:val")) or None

    def resolve(self, style_id: str | None) -> StyleEntry | None:
        """按 python-docx get_by_id 语义解析：None 或未知 id 回落默认段落样式。"""
        if style_id is not None:
            entry = self._entries.get(style_id)
            if entry is not None:
                return entry
        if self._default_id is not None:
            return self._entries.get(self._default_id)
        return None

    def iter_chain(self, style_id: str | None):
        """从解析结果沿 basedOn 链向上遍历，带 visited 保护。"""
        entry = self.resolve(style_id)
        visited: set[str] = set()
        while entry is not None and entry.style_id not in visited:
            visited.add(entry.style_id)
            yield entry
            entry = self._entries.get(entry.based_on) if entry.based_on else None


# 部件 → (styles 元素, 建索引时的子节点数, 索引)。styles 元素引用一并保存：
# 指纹校验直接 len() 该元素，避免每次都走一遍部件关系查找。
_CACHE: "WeakKeyDictionary" = WeakKeyDictionary()


def index_for_paragraph(para) -> StyleIndex:
    part = para.part
    cached = _CACHE.get(part)
    if cached is not None:
        styles_element, fingerprint, index = cached
        if len(styles_element) == fingerprint:
            return index
    styles_element = part.styles.element
    index = StyleIndex(styles_element)
    _CACHE[part] = (styles_element, len(styles_element), index)
    return index
