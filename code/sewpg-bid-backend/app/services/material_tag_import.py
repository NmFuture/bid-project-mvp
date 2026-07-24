"""技术标素材库「导入标签」核心逻辑。

把一份 Excel 清单（文件名称 + 属性1/2/3）批量匹配到素材库文件，并以
追加去重的方式写入 ``ext_fields.tags``。

设计要点：
- 解析与匹配是确定性纯函数，便于单测。
- 文件名匹配忽略扩展名（用 ``PurePosixPath.stem``）。
- 同名多个文件时，用 Excel 的目录层级列（A-E）末级与候选 ``folderPath``
  末级比对消歧；仍无法唯一定位则归为 ``ambiguous`` 交前端人工选。
- tag 合并复用现有 ``normalize_material_tags``，与前端 ``normalizeTagList``
  语义一致（按中英文逗号/分号/换行拆分、去空白、去重、上限 20 个）。
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.material_tags import normalize_material_tags
from app.services.peripheral import PeripheralError

# Excel 表头识别用的关键词
_FILE_NAME_HEADERS = ("文件名称", "文件名", "名称")
# 属性列表头：以「属性」开头（属性1/属性2…）或命中这些同义词
_TAG_HEADER_PREFIX = "属性"
_TAG_HEADER_ALIASES = ("标签", "分类", "关键词", "tag", "tags")
# file_name 等于/开头是这些占位文本的行直接跳过（不当成真实文件名去匹配）
_PLACEHOLDER_PREFIXES = ("待填写", "待补充", "待定", "暂无")
_PLACEHOLDER_EXACT = {"无", "无.", "/", "\\", "-", "—", "n/a", "na", "null", "none", "暂无", "/无"}
# 全角→半角的常见标点/数字映射，用于把 Excel 与库里「语义同名」的差异抹平。
# 例：EW6．25-220（全角点）↔ EW6.25-220，变桨系统（一）↔ 变桨系统(一)。
_FULLWIDTH_MAP = {
    "（": "(", "）": ")", "［": "[", "］": "]", "｛": "{", "｝": "}",
    "．": ".", "，": ",", "、": ",", "：": ":", "；": ";",
    "－": "-", "—": "-", "～": "~", "／": "/", "＼": "\\",
    "　": " ",
}
# 全角 ＡＺ ａｚ ０９ → 半角（U+FF01..U+FF5E 段，统一减 0xFEE0）
for _cp in range(0xFF01, 0xFF5F):
    _FULLWIDTH_MAP.setdefault(chr(_cp), chr(_cp - 0xFEE0))
# 仅当文件名以这些「真实扩展名」结尾时才剥离；避免把机型号里的小数点
# （如 EW6.25-220）误判成扩展名而截断文件名。
_KNOWN_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "xlsm", "ppt", "pptx", "txt", "csv",
    "png", "jpg", "jpeg", "webp", "bmp", "gif", "tif", "tiff",
    "zip", "rar", "7z", "dwg", "dxf",
}


@dataclass
class TagImportRow:
    """Excel 中的一行解析结果。"""

    row_index: int  # Excel 中的 1-based 行号（含表头），用于回显定位
    file_name: str  # F 列：用于匹配的文件名（不含扩展名约定）
    tags: list[str]  # 属性1/2/3 等列合并去重后的 tag
    level_path: list[str] = field(default_factory=list)  # A-E 非空目录层级

    def to_dict(self) -> dict[str, Any]:
        return {
            "rowIndex": self.row_index,
            "fileName": self.file_name,
            "tags": self.tags,
            "levelPath": self.level_path,
        }


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("　", " ")
    return re.sub(r"\s+", " ", text).strip()


def _fold(text: str) -> str:
    """把全角标点/数字/字母折叠成半角，便于「语义同名」比对。

    只做字符映射，不删任何字符——保留原长度语义，避免误把不同名字折成同名。
    """

    return "".join(_FULLWIDTH_MAP.get(ch, ch) for ch in str(text or ""))


def _file_stem(name: str) -> str:
    """去掉「真实扩展名」并归一，用作匹配键。

    只剥离 ``_KNOWN_EXTENSIONS`` 里的扩展名，绝不能用 ``PurePosixPath.stem``——
    机型号（如 ``EW6.25-220``）里的小数点会被它当成扩展名分隔符，导致文件名
    被截断（``EW6.25-220机型参数`` 会变成 ``EW6``）。
    """

    text = _cell_text(name)
    dot = text.rfind(".")
    if dot > 0:
        ext = text[dot + 1 :].strip().lower()
        if ext in _KNOWN_EXTENSIONS:
            text = text[:dot]
    return _cell_text(text)


def _match_key(name: str) -> str:
    """匹配用的归一键：去扩展名 + 全角折半角 + casefold。

    全角折叠让 ``EW6．25-220``（全角点）能与 ``EW6.25-220`` 精确命中，
    ``变桨系统（一）`` 能与 ``变桨系统(一)`` 命中，而不必掉进模糊匹配。
    """

    return _fold(_file_stem(name)).casefold()


def _is_placeholder(file_name: str) -> bool:
    """判断文件名是否是占位/空值，不应作为真实文件去匹配。"""

    if any(file_name.startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES):
        return True
    return _fold(file_name).strip().casefold() in _PLACEHOLDER_EXACT


def _is_tag_header(text: str) -> bool:
    """判断某列表头是否是「属性/标签」列。

    主格式是「属性1/属性2…」；同时兼容标签N/分类/关键词等同义列名。
    需注意避免把文件名列本身吃进来（调用方已用 ``i != file_col`` 排除）。
    """

    if not text:
        return False
    if text.startswith(_TAG_HEADER_PREFIX):
        return True
    folded = _fold(text).casefold()
    # 允许「标签」「标签1」「分类」「关键词」「tag」「tags」等，及其带序号变体
    base = re.sub(r"[\s\d]+$", "", folded)
    return base in _TAG_HEADER_ALIASES


# 标签值里需要剥掉的序号前缀：1. / 1、/ 1) / （1）/ 一、 等
_TAG_PREFIX_RE = re.compile(r"^\s*(?:[（(]?\d+[)）.．、:：]|[一二三四五六七八九十]+[、.．:：])\s*")


def _clean_tag_value(text: str) -> list[str]:
    """对单个属性单元格做更强清洗：拆顿号/斜杠、去序号前缀、丢纯符号。

    返回该单元格里拆出的若干 tag 候选（未做全局去重，交 normalize 收尾）。
    """

    folded = _fold(text)
    parts = re.split(r"[、,；;/\n\r\t]+", folded)
    out: list[str] = []
    for part in parts:
        item = _TAG_PREFIX_RE.sub("", _cell_text(part))
        # 丢掉清洗后只剩标点/符号的碎片（如 "-"、"()"、"."）
        if not item or not re.search(r"[\w一-鿿]", item):
            continue
        out.append(item)
    return out


def _locate_header(rows: list[tuple[Any, ...]]) -> tuple[int, dict[str, int]]:
    """在前若干行中定位表头，返回 (表头行下标, 列名->列号 映射)。

    通过「同时包含文件名称列和至少一个属性列」来识别表头。
    """

    for idx, row in enumerate(rows[:10]):
        cells = [_cell_text(cell) for cell in row]
        file_col = next(
            (i for i, text in enumerate(cells) if text in _FILE_NAME_HEADERS),
            None,
        )
        tag_cols = [
            i
            for i, text in enumerate(cells)
            if i != file_col and _is_tag_header(text)
        ]
        if file_col is not None and tag_cols:
            mapping = {"file": file_col, "tags": tag_cols}
            # 目录层级列 = 文件名列之前、且不是属性列的所有列
            tag_set = set(tag_cols)
            mapping["levels"] = [i for i in range(0, file_col) if i not in tag_set]
            return idx, mapping
    raise PeripheralError(
        400,
        "未能在 Excel 中识别表头，请确认包含「文件名称」和「属性1/2/3」列。",
        "TAG_IMPORT_HEADER_NOT_FOUND",
    )


def parse_tag_excel(file_bytes: bytes) -> list[TagImportRow]:
    """解析 Excel 字节流，返回有效的导入行。"""

    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - 环境保证已安装
        raise PeripheralError(500, "服务端缺少 Excel 解析依赖。", "TAG_IMPORT_DEPENDENCY") from exc

    try:
        workbook = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    except Exception as exc:
        raise PeripheralError(400, "Excel 文件无法解析，请确认格式为 .xlsx。", "TAG_IMPORT_PARSE_FAILED") from exc

    worksheet = workbook.worksheets[0] if workbook.worksheets else None
    if worksheet is None:
        raise PeripheralError(400, "Excel 中没有可用的工作表。", "TAG_IMPORT_EMPTY_WORKBOOK")

    rows = list(worksheet.iter_rows(values_only=True))
    if not rows:
        raise PeripheralError(400, "Excel 内容为空。", "TAG_IMPORT_EMPTY_SHEET")

    header_idx, mapping = _locate_header(rows)
    file_col: int = mapping["file"]
    tag_cols: list[int] = mapping["tags"]
    level_cols: list[int] = mapping["levels"]

    parsed: list[TagImportRow] = []
    for offset, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
        file_name = _cell_text(row[file_col]) if file_col < len(row) else ""
        if not file_name:
            continue
        if _is_placeholder(file_name):
            continue
        tag_values: list[str] = []
        for col in tag_cols:
            if col < len(row):
                tag_values.extend(_clean_tag_value(_cell_text(row[col])))
        tags = normalize_material_tags(tag_values)
        if not tags:
            continue
        level_path = [
            _cell_text(row[col]) for col in level_cols if col < len(row) and _cell_text(row[col])
        ]
        parsed.append(
            TagImportRow(
                row_index=offset,
                file_name=file_name,
                tags=tags,
                level_path=level_path,
            )
        )
    return parsed


def _index_files_by_match_key(files: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for item in files:
        key = _match_key(str(item.get("name") or ""))
        if not key:
            continue
        index.setdefault(key, []).append(item)
    return index


def _disambiguate(candidates: list[dict[str, Any]], level_path: list[str]) -> dict[str, Any] | None:
    """用 Excel 目录层级末级匹配候选 folderPath 的某一级，能唯一定位则返回。"""

    if not level_path:
        return None
    # 从最深一级目录词往上找，取第一个能唯一命中的层级词
    for level in reversed(level_path):
        level_key = _fold(_cell_text(level)).casefold()
        if not level_key:
            continue
        hits = [
            item
            for item in candidates
            if level_key
            in {
                _fold(seg).casefold()
                for seg in str(item.get("folderPath") or "").split("/")
                if seg
            }
        ]
        if len(hits) == 1:
            return hits[0]
    return None


def _merge_preview(existing: Any, incoming: list[str], *, mode: str = "merge") -> dict[str, Any]:
    existing_tags = normalize_material_tags(existing)
    incoming_tags = normalize_material_tags(incoming)
    if mode == "overwrite":
        # 覆盖模式:Excel 写了标签的行整条替换;留空的行保留原标签(防止空格误删)。
        merged = incoming_tags if incoming_tags else existing_tags
    else:
        merged = normalize_material_tags([*existing_tags, *incoming_tags])
    added = [tag for tag in merged if tag not in existing_tags]
    removed = [tag for tag in existing_tags if tag not in merged]
    return {
        "existingTags": existing_tags,
        "incomingTags": incoming_tags,
        "mergedTags": merged,
        "addedTags": added,
        "removedTags": removed,
    }


def _matched_entry(row: TagImportRow, item: dict[str, Any], *, mode: str = "merge") -> dict[str, Any]:
    merge = _merge_preview(item.get("tags"), row.tags, mode=mode)
    return {
        **row.to_dict(),
        "fileId": str(item.get("id") or ""),
        "matchedName": str(item.get("name") or ""),
        "folderPath": str(item.get("folderPath") or ""),
        **merge,
    }


def _candidate_brief(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "fileId": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "folderPath": str(item.get("folderPath") or ""),
        "tags": normalize_material_tags(item.get("tags")),
    }


def build_preview(rows: list[TagImportRow], files: list[dict[str, Any]], *, mode: str = "merge") -> dict[str, Any]:
    """把解析行与目标子树文件做匹配，返回分区预览。"""

    index = _index_files_by_match_key(files)
    matched: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for row in rows:
        candidates = index.get(_match_key(row.file_name), [])
        if len(candidates) == 1:
            matched.append(_matched_entry(row, candidates[0], mode=mode))
        elif len(candidates) > 1:
            picked = _disambiguate(candidates, row.level_path)
            if picked is not None:
                matched.append(_matched_entry(row, picked, mode=mode))
            else:
                ambiguous.append(
                    {
                        **row.to_dict(),
                        "candidates": [_candidate_brief(item) for item in candidates],
                    }
                )
        else:
            unmatched.append(row.to_dict())

    return {
        "matched": matched,
        "ambiguous": ambiguous,
        "unmatched": unmatched,
        "fuzzy": [],
        "stats": {
            "totalRows": len(rows),
            "matched": len(matched),
            "ambiguous": len(ambiguous),
            "unmatched": len(unmatched),
            "candidateFiles": len(files),
        },
    }
