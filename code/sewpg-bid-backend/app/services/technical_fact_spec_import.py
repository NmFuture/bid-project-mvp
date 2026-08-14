from __future__ import annotations

"""技术标项目事实表字段清单 xlsx → spec JSON 的解析核心。

清单只有全局一份，由素材库「规则」tab 和设置页上传，两个入口共用本模块解析。

清单列（Sheet1，首行表头）：
    序号 / 类型 / 文件夹 / 文件名 / 占位符内容 / 引用文件

按表头名定位列，不依赖列序；缺可选列（序号/类型/文件夹）不报错。

字段名取自「占位符内容」——剥掉方括号与「待填写」后缀后的正文。同一事实会在多个文件
里各填一遍（实测 132 行「待填写」只对应 59 个不同字段），故按字段名归并成一个 spec，
targetFile / placeholder 存分号分隔的多值，两列下标一一对应，与下游
bid-tech-word-placeholder-filler 的 split_spec_cell 一格多值约定一致。

「类型」为「待插入」的行不是事实字段，是整文件插入指令，走 manifest 的 embedSources
独立通道（technical_gap_ai_fill 直接扫 Word 文档本身），故整行跳过。

生成的 spec 字段：
    seq, key, label, reviewLabel, targetFile, sourceFile, placeholder, note,
    referenceFile, valueRequired, sourceKind, aliases
"""

import json
import re
from pathlib import Path
from typing import Any

import openpyxl

EXPECTED_HEADER = ["序号", "类型", "文件夹", "文件名", "占位符内容", "引用文件"]

# 一格多值分隔符：与下游 split_spec_cell 的 [；;\n] 拆分口径一致
MULTI_VALUE_SEPARATOR = ";"

# 「类型」列取该值的行是整文件插入指令，不进事实表
EMBED_ROW_TYPE = "待插入"

# 必需列（缺失即报错）：列键 → 表头名，供报错文案使用。
REQUIRED_COLUMNS = (
    ("target_file", "文件名"),
    ("placeholder", "占位符内容"),
    ("reference_file", "引用文件"),
)

# 引用文件 → 来源类别
SOURCE_KIND_RULES = [
    ("招标文件", "tender"),
    ("项目定制", "material"),
    ("认证证书", "cert"),
    ("平台输入", "platform"),
    ("自动生成", "derived"),
]

_BRACKET_PREFIX_RE = re.compile(r"^[\[【]\s*")
_BRACKET_SUFFIX_RE = re.compile(r"\s*[\]】]$")
_FILL_PREFIX_RE = re.compile(r"^(待填写|缺失)[:：]\s*")
_FILL_SUFFIX_RE = re.compile(r"[，,、:：\s]*(待填写|待补充|待确认|待插入)$")


class FactSpecImportError(ValueError):
    """清单文件不合法（无法解析/表头不符/内容为空/序号无效）。"""


def normalize_key(text: str) -> str:
    """生成字段稳定键：去空白、全角括号转半角、去常见标点。"""
    text = re.sub(r"\s+", "", text or "")
    text = text.replace("（", "(").replace("）", ")")
    return re.sub(r"[，,、;；:：/\\\-—_]+", "", text).lower()


def placeholder_label(raw: Any) -> str:
    """占位符原文 → 字段名：剥外层方括号与「待填写」类前后缀。

    与 bid-tech-word-placeholder-filler/scripts/run_from_manifest.py 的同名函数保持同一
    套剥离规则，清单侧认出的字段名才和填写侧对得上。
    """
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    text = _BRACKET_SUFFIX_RE.sub("", _BRACKET_PREFIX_RE.sub("", text)).strip()
    text = _FILL_PREFIX_RE.sub("", text).strip()
    return _FILL_SUFFIX_RE.sub("", text).strip()


def split_multi_value(value: Any) -> list[str]:
    """一格多值拆回列表：分号（全/半角）与换行都算分隔符，与下游 split_spec_cell 同口径。"""
    text = str(value or "").replace("　", " ").replace("\xa0", " ")
    return [part.strip() for part in re.split(r"[；;\n]+", text) if part.strip()]


def classify_source(reference_file: str) -> str:
    """来源文件列 → 来源类别。

    「/」与整格留空语义不同：前者是编制清单时未指定来源，字段仍需取值，交给 AI 在
    素材范围内找；后者才是模板占位，不进取数流程。
    """
    ref = (reference_file or "").strip()
    if not ref:
        return "template"
    if ref == "/":
        return "unspecified"
    for prefix, kind in SOURCE_KIND_RULES:
        if ref.startswith(prefix):
            return kind
    return "material"


def cell_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def resolve_columns(header: list[str]) -> dict[str, int | None]:
    """表头名 → 列号。可选列缺失返回 None，必需列缺失抛 FactSpecImportError。"""
    index: dict[str, int] = {}
    for position, name in enumerate(header):
        if name and name not in index:
            index[name] = position
    columns: dict[str, int | None] = {
        "seq": index.get("序号"),
        "row_type": index.get("类型"),
        "target_file": index.get("文件名"),
        "placeholder": index.get("占位符内容"),
        "reference_file": index.get("引用文件"),
    }
    missing = [name for key, name in REQUIRED_COLUMNS if columns.get(key) is None]
    if missing:
        raise FactSpecImportError(
            f"清单缺少必需列 {missing}；期望表头 {EXPECTED_HEADER}，实际 {header}"
        )
    return columns


def cell_at(row: tuple[Any, ...], position: int | None) -> str:
    if position is None or position >= len(row):
        return ""
    return cell_text(row[position])


def row_seq(row: tuple[Any, ...], position: int | None, row_index: int) -> int:
    """序号列缺失或本行留空时退化成行号；序号只用于排序与定位，不参与取值。"""
    if position is None or position >= len(row) or cell_text(row[position]) == "":
        return row_index - 1
    raw = row[position]
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise FactSpecImportError(f"第 {row_index} 行序号无效：{raw!r}") from exc


def _finalize(pending: dict[str, Any]) -> dict[str, Any]:
    """归并态（多值列表）→ 落盘态（分号分隔字符串），并按引用文件定来源类别。"""
    target_file = MULTI_VALUE_SEPARATOR.join(pending["targetFile"])
    source_kind = classify_source(pending["referenceFile"])
    return {
        "seq": pending["seq"],
        "key": pending["key"],
        "label": pending["label"],
        "reviewLabel": pending["reviewLabel"],
        "targetFile": target_file,
        # 兼容既有 spec/产物字段；其语义一直是待填写目标文件，不是取数来源。
        "sourceFile": target_file,
        "placeholder": MULTI_VALUE_SEPARATOR.join(pending["placeholder"]),
        "note": pending["note"],
        "referenceFile": pending["referenceFile"],
        "valueRequired": source_kind != "template",
        "sourceKind": source_kind,
        "aliases": [],
    }


def import_specs(xlsx_path: Path | str, output_path: Path | str | None = None) -> list[dict[str, Any]]:
    """解析清单 xlsx 为 spec list；给定 output_path 时同时写 JSON 文件。

    解析失败抛 FactSpecImportError（CLI 与上传接口各自转成退出码/400）。
    """
    path = Path(xlsx_path)
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:
        raise FactSpecImportError(f"无法解析清单文件（需为 .xlsx）：{path.name}") from exc
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise FactSpecImportError(f"清单为空: {path.name}")
    header = [cell_text(c) for c in rows[0]]
    columns = resolve_columns(header)

    # 按 key 归并（而非 label 原文）：normalize_key 会把「轮毂高度（m）」和「轮毂高度,m」
    # 归一成同一个键，按 label 归并会留下两个 spec 却共用一个键，下游按键取值即冲突。
    merged: dict[str, dict[str, Any]] = {}
    for row_index, row in enumerate(rows[1:], start=2):
        if cell_at(row, columns["row_type"]) == EMBED_ROW_TYPE:
            continue
        placeholder = cell_at(row, columns["placeholder"])
        label = placeholder_label(placeholder)
        if not label:
            continue
        seq = row_seq(row, columns["seq"], row_index)
        target_file = cell_at(row, columns["target_file"])
        reference_file = cell_at(row, columns["reference_file"])
        pending = merged.get(normalize_key(label))
        if pending is None:
            merged[normalize_key(label)] = {
                "seq": seq,
                "key": normalize_key(label),
                "label": label,
                "reviewLabel": "",
                "targetFile": [target_file],
                "placeholder": [placeholder],
                "note": cell_at(row, columns["row_type"]),
                "referenceFile": reference_file,
            }
            continue
        # 同一事实在多个文件里各填一遍：位置逐个累加，两列下标必须一一对应，故不去重
        pending["targetFile"].append(target_file)
        pending["placeholder"].append(placeholder)
        pending["seq"] = min(pending["seq"], seq)
        # 先出现的行未写引用文件时，由后续同名行补上，否则整字段会被误判成模板占位
        if not pending["referenceFile"]:
            pending["referenceFile"] = reference_file

    specs = [_finalize(pending) for pending in merged.values()]
    if not specs:
        raise FactSpecImportError(f"清单未解析出任何字段: {path.name}")

    if output_path is not None:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(specs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return specs
