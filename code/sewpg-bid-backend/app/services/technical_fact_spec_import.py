from __future__ import annotations

"""技术标规则表 xlsx → spec / 插入规则 JSON 的解析核心。

规则表只有全局一份，由素材库「规则」tab 和设置页上传，两个入口共用本模块解析。
一份表按类别分 sheet，每类一个：目前是「待填写」「待插入」，将来加类别就加 sheet。
不认识的 sheet 一律跳过不报错——业务方加临时备注页、或先加了代码还没支持的新类别，
都不该让整份表传不上去。识别与跳过结果由 import_rule_book 报给调用方，不静默。

「待填写」sheet 列（首行表头）：
    序号 / 文件夹 / 文件名 / 占位符内容 / 引用文件

按表头名定位列，不依赖列序；缺可选列（序号/文件夹）不报错。

字段名取自「占位符内容」——剥掉方括号与「待填写」后缀后的正文。同一事实会在多个文件
里各填一遍（实测 132 行「待填写」只对应 59 个不同字段），故按字段名归并成一个 spec，
targetFile / placeholder 存分号分隔的多值，两列下标一一对应，与下游
bid-tech-word-placeholder-filler 的 split_spec_cell 一格多值约定一致。

「待插入」sheet 列（首行表头）：
    文件夹 / 文件名 / 占位符内容 / 素材 / 起点标题 / 终点标题

一行一个插入动作，**不归并**：同一份素材要插进 X2 和 X3 两个专题就是两行两次插入，
按名字合并会让其中一份 Word 的占位符永远没人管，还不报错。

生成的 spec 字段：
    seq, key, label, reviewLabel, targetFile, sourceFile, placeholder, note,
    referenceFile, valueRequired, sourceKind, aliases
生成的插入规则字段：
    seq, folder, targetFile, placeholder, material, headingStart, headingEnd
"""

import json
import re
from pathlib import Path
from typing import Any

import openpyxl

EXPECTED_HEADER = ["序号", "文件夹", "文件名", "占位符内容", "引用文件"]
EMBED_EXPECTED_HEADER = ["文件夹", "文件名", "占位符内容", "素材", "起点标题", "终点标题"]

# sheet 名即类别，代码按名字认；改名等于换类别，业务方不能随手改
SHEET_FILL = "待填写"
SHEET_EMBED = "待插入"

# 一格多值分隔符：与下游 split_spec_cell 的 [；;\n] 拆分口径一致
MULTI_VALUE_SEPARATOR = ";"

# 分 sheet 前用「类型」列区分两类，分完这个词只该出现在待插入 sheet 里
EMBED_ROW_TYPE = "待插入"

# 必需列（缺失即报错）：列键 → 表头名，供报错文案使用。
REQUIRED_COLUMNS = (
    ("target_file", "文件名"),
    ("placeholder", "占位符内容"),
    ("reference_file", "引用文件"),
)
EMBED_REQUIRED_COLUMNS = (
    ("target_file", "文件名"),
    ("placeholder", "占位符内容"),
    ("material", "素材"),
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


def _header_index(header: list[str]) -> dict[str, int]:
    index: dict[str, int] = {}
    for position, name in enumerate(header):
        if name and name not in index:
            index[name] = position
    return index


def resolve_columns(header: list[str]) -> dict[str, int | None]:
    """「待填写」表头名 → 列号。可选列缺失返回 None，必需列缺失抛 FactSpecImportError。"""
    index = _header_index(header)
    columns: dict[str, int | None] = {
        "seq": index.get("序号"),
        "target_file": index.get("文件名"),
        "placeholder": index.get("占位符内容"),
        "reference_file": index.get("引用文件"),
    }
    missing = [name for key, name in REQUIRED_COLUMNS if columns.get(key) is None]
    if missing:
        raise FactSpecImportError(
            f"「{SHEET_FILL}」缺少必需列 {missing}；期望表头 {EXPECTED_HEADER}，实际 {header}"
        )
    return columns


def resolve_embed_columns(header: list[str]) -> dict[str, int | None]:
    """「待插入」表头名 → 列号；起点/终点缺列即视为整份插入，不报错。"""
    index = _header_index(header)
    columns: dict[str, int | None] = {
        "folder": index.get("文件夹"),
        "target_file": index.get("文件名"),
        "placeholder": index.get("占位符内容"),
        "material": index.get("素材"),
        "heading_start": index.get("起点标题"),
        "heading_end": index.get("终点标题"),
    }
    missing = [name for key, name in EMBED_REQUIRED_COLUMNS if columns.get(key) is None]
    if missing:
        raise FactSpecImportError(
            f"「{SHEET_EMBED}」缺少必需列 {missing}；期望表头 {EMBED_EXPECTED_HEADER}，实际 {header}"
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


def _load_workbook(path: Path) -> Any:
    try:
        return openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:
        raise FactSpecImportError(f"无法解析规则表（需为 .xlsx）：{path.name}") from exc


def _sheet_rows(wb: Any, sheet_name: str) -> list[tuple[Any, ...]] | None:
    """按名字取 sheet 全部行；没有这个 sheet 返回 None（区别于 sheet 存在但为空）。"""
    if sheet_name not in wb.sheetnames:
        return None
    return list(wb[sheet_name].iter_rows(values_only=True))


def _parse_fill_rows(rows: list[tuple[Any, ...]], source_name: str) -> list[dict[str, Any]]:
    if not rows:
        raise FactSpecImportError(f"「{SHEET_FILL}」为空: {source_name}")
    header = [cell_text(c) for c in rows[0]]
    columns = resolve_columns(header)

    # 按 key 归并（而非 label 原文）：normalize_key 会把「轮毂高度（m）」和「轮毂高度,m」
    # 归一成同一个键，按 label 归并会留下两个 spec 却共用一个键，下游按键取值即冲突。
    merged: dict[str, dict[str, Any]] = {}
    for row_index, row in enumerate(rows[1:], start=2):
        placeholder = cell_at(row, columns["placeholder"])
        # 占位符后缀是类型的权威标记。分 sheet 后待插入行写进这里，会被 placeholder_label
        # 剥掉后缀当成事实字段，静默多出一个永远取不到值的字段，故显式拒绝。
        if EMBED_ROW_TYPE in placeholder:
            raise FactSpecImportError(
                f"「{SHEET_FILL}」第 {row_index} 行占位符「{placeholder}」是待插入，"
                f"应放在「{SHEET_EMBED}」sheet。"
            )
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
                # 分 sheet 前这里存「类型」列的值（恒为「待填写」）。事实表的 notes 本是
                # 给人写「为什么本项目不需要这个字段」的，留空才让人和 AI 写得进去。
                "note": "",
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
        raise FactSpecImportError(f"「{SHEET_FILL}」未解析出任何字段: {source_name}")
    return specs


def _parse_embed_rows(rows: list[tuple[Any, ...]], source_name: str) -> list[dict[str, Any]]:
    """「待插入」行 → 插入规则。一行一个动作，不按素材名归并。"""
    if not rows:
        return []
    header = [cell_text(c) for c in rows[0]]
    columns = resolve_embed_columns(header)

    rules: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows[1:], start=2):
        placeholder = cell_at(row, columns["placeholder"])
        if not placeholder:
            continue
        material = cell_at(row, columns["material"])
        if not material:
            raise FactSpecImportError(
                f"「{SHEET_EMBED}」第 {row_index} 行占位符「{placeholder}」未填「素材」。"
            )
        start = cell_at(row, columns["heading_start"])
        end = cell_at(row, columns["heading_end"])
        if end and not start:
            raise FactSpecImportError(
                f"「{SHEET_EMBED}」第 {row_index} 行只填了终点标题「{end}」没填起点标题。"
            )
        rules.append(
            {
                "seq": len(rules) + 1,
                "folder": cell_at(row, columns["folder"]),
                "targetFile": cell_at(row, columns["target_file"]),
                "placeholder": placeholder,
                "material": material,
                # 起点填了终点留空＝只插这一节，闭区间收敛成单点，与下游 headingRange 同口径
                "headingStart": start,
                "headingEnd": end or start,
            }
        )
    return rules


def import_specs(xlsx_path: Path | str, output_path: Path | str | None = None) -> list[dict[str, Any]]:
    """解析规则表「待填写」sheet 为 spec list；给定 output_path 时同时写 JSON 文件。

    解析失败抛 FactSpecImportError（CLI 与上传接口各自转成退出码/400）。
    """
    path = Path(xlsx_path)
    rows = _sheet_rows(_load_workbook(path), SHEET_FILL)
    if rows is None:
        raise FactSpecImportError(f"规则表缺少「{SHEET_FILL}」sheet: {path.name}")
    specs = _parse_fill_rows(rows, path.name)
    if output_path is not None:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(specs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return specs


def import_embed_rules(xlsx_path: Path | str) -> list[dict[str, Any]]:
    """解析规则表「待插入」sheet；没有这个 sheet 返回空列表（该类别尚未维护，不是错）。"""
    path = Path(xlsx_path)
    rows = _sheet_rows(_load_workbook(path), SHEET_EMBED)
    return [] if rows is None else _parse_embed_rows(rows, path.name)


def import_rule_book(xlsx_path: Path | str) -> dict[str, Any]:
    """一次解析整份规则表，返回两类规则与 sheet 识别结果。

    跳过的 sheet 一并返回：sheet 名认错一个字（「待插 入」）会被当成不认识而静默跳过，
    调用方要把这份名单展示给人，否则传上去了没生效也看不出来。
    """
    path = Path(xlsx_path)
    wb = _load_workbook(path)
    fill_rows = _sheet_rows(wb, SHEET_FILL)
    if fill_rows is None:
        raise FactSpecImportError(
            f"规则表缺少「{SHEET_FILL}」sheet: {path.name}（实际 sheet：{wb.sheetnames}）"
        )
    embed_rows = _sheet_rows(wb, SHEET_EMBED)
    return {
        "specs": _parse_fill_rows(fill_rows, path.name),
        "embedRules": [] if embed_rows is None else _parse_embed_rows(embed_rows, path.name),
        "recognizedSheets": [n for n in wb.sheetnames if n in (SHEET_FILL, SHEET_EMBED)],
        "skippedSheets": [n for n in wb.sheetnames if n not in (SHEET_FILL, SHEET_EMBED)],
    }
