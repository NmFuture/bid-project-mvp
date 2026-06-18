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
_TAG_HEADER_PREFIX = "属性"
# file_name 以这些前缀开头的占位行直接跳过
_PLACEHOLDER_PREFIXES = ("待填写",)
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
    """匹配用的归一键：去扩展名 + casefold（中文不受影响，兼容英文大小写）。"""

    return _file_stem(name).casefold()


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
        tag_cols = [i for i, text in enumerate(cells) if text.startswith(_TAG_HEADER_PREFIX)]
        if file_col is not None and tag_cols:
            mapping = {"file": file_col, "tags": tag_cols}
            # 目录层级列 = 文件名列之前的所有列
            mapping["levels"] = list(range(0, file_col))
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
        if any(file_name.startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES):
            continue
        tag_values = [
            _cell_text(row[col]) for col in tag_cols if col < len(row) and _cell_text(row[col])
        ]
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
        level_key = _cell_text(level).casefold()
        if not level_key:
            continue
        hits = [
            item
            for item in candidates
            if level_key
            in {seg.casefold() for seg in str(item.get("folderPath") or "").split("/") if seg}
        ]
        if len(hits) == 1:
            return hits[0]
    return None


def _merge_preview(existing: Any, incoming: list[str]) -> dict[str, Any]:
    existing_tags = normalize_material_tags(existing)
    merged = normalize_material_tags([*existing_tags, *incoming])
    added = [tag for tag in merged if tag not in existing_tags]
    return {
        "existingTags": existing_tags,
        "incomingTags": normalize_material_tags(incoming),
        "mergedTags": merged,
        "addedTags": added,
    }


def _matched_entry(row: TagImportRow, item: dict[str, Any]) -> dict[str, Any]:
    merge = _merge_preview(item.get("tags"), row.tags)
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


def build_preview(rows: list[TagImportRow], files: list[dict[str, Any]]) -> dict[str, Any]:
    """把解析行与目标子树文件做匹配，返回分区预览。"""

    index = _index_files_by_match_key(files)
    matched: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for row in rows:
        candidates = index.get(_match_key(row.file_name), [])
        if len(candidates) == 1:
            matched.append(_matched_entry(row, candidates[0]))
        elif len(candidates) > 1:
            picked = _disambiguate(candidates, row.level_path)
            if picked is not None:
                matched.append(_matched_entry(row, picked))
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
