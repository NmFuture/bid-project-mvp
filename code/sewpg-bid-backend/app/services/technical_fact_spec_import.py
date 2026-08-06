from __future__ import annotations

"""技术标项目事实表字段清单 xlsx → spec JSON 的解析核心。

Docker 部署只 COPY app/，scripts/ 不是运行时可依赖的包路径，因此解析逻辑放在
app 包内：设置页上传接口（app/api/routes/settings.py）与
scripts/import_technical_fact_specs.py CLI 共用本模块。

清单列（Sheet1，首行表头）：
    序号 / 待填写文件 / 原占位符位置 / 实际要填写的字段 / 必要说明 / 复核 / 来源文件

按表头名定位列，不依赖列序；缺可选列（序号/必要说明/复核）不报错。
兼容历史表头：第 2 列“来源文件”、第 7 列“引用文件”。历史命名中的
“来源文件”实际表示待填写目标文件，导入后仍保留 sourceFile 兼容字段。

生成的 spec 字段：
    seq, key, label, reviewLabel, targetFile, sourceFile, placeholder, note,
    needsConfirmation, referenceFile, valueRequired, sourceKind, aliases
"""

import json
import re
from pathlib import Path
from typing import Any

import openpyxl

EXPECTED_HEADER = ["序号", "待填写文件", "原占位符位置", "实际要填写的字段", "必要说明", "复核", "来源文件"]
LEGACY_HEADER = ["序号", "来源文件", "原占位符位置", "实际要填写的字段", "必要说明", "复核", "引用文件"]

# 必需列（缺失即报错）：列键 → 表头名，供报错文案使用。
REQUIRED_COLUMNS = (
    ("target_file", "待填写文件"),
    ("placeholder", "原占位符位置"),
    ("label", "实际要填写的字段"),
    ("reference_file", "来源文件"),
)

# 引用文件 → 来源类别
SOURCE_KIND_RULES = [
    ("招标文件", "tender"),
    ("项目定制", "material"),
    ("认证证书", "cert"),
    ("平台输入", "platform"),
    ("自动生成", "derived"),
]


class FactSpecImportError(ValueError):
    """清单文件不合法（无法解析/表头不符/内容为空/序号无效）。"""


def normalize_key(text: str) -> str:
    """生成字段稳定键：去空白、全角括号转半角、去常见标点。"""
    text = re.sub(r"\s+", "", text or "")
    text = text.replace("（", "(").replace("）", ")")
    return re.sub(r"[，,、;；:：/\\\-—_]+", "", text).lower()


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
        "placeholder": index.get("原占位符位置"),
        "label": index.get("实际要填写的字段"),
        "note": index.get("必要说明"),
        "review": index.get("复核"),
    }
    # 「来源文件」在两种表头里指代不同：新表头有独立的「待填写文件」列，
    # 「来源文件」是取数来源；历史表头没有「待填写文件」，第 2 列的
    # 「来源文件」才是待填写目标，取数来源叫「引用文件」。
    if "待填写文件" in index:
        columns["target_file"] = index["待填写文件"]
        columns["reference_file"] = index.get("来源文件")
    else:
        columns["target_file"] = index.get("来源文件")
        columns["reference_file"] = index.get("引用文件")
    missing = [name for key, name in REQUIRED_COLUMNS if columns.get(key) is None]
    if missing:
        raise FactSpecImportError(
            f"清单缺少必需列 {missing}；期望表头 {EXPECTED_HEADER}"
            f"（兼容历史表头 {LEGACY_HEADER}），实际 {header}"
        )
    return columns


def cell_at(row: tuple[Any, ...], position: int | None) -> str:
    if position is None or position >= len(row):
        return ""
    return cell_text(row[position])


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

    specs: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows[1:], start=2):
        label = cell_at(row, columns["label"])
        if not label:
            continue
        note = cell_at(row, columns["note"])
        target_file = cell_at(row, columns["target_file"])
        reference_file = cell_at(row, columns["reference_file"])
        source_kind = classify_source(reference_file)
        # 无序号列时用行号顶上：序号只用于排序与定位，不参与取值。
        if columns["seq"] is None:
            seq = row_index - 1
        else:
            raw_seq = row[columns["seq"]] if columns["seq"] < len(row) else None
            try:
                seq = int(raw_seq)
            except (TypeError, ValueError) as exc:
                raise FactSpecImportError(f"第 {row_index} 行序号无效：{raw_seq!r}") from exc
        specs.append(
            {
                "seq": seq,
                "key": normalize_key(label),
                "label": label,
                "reviewLabel": cell_at(row, columns["review"]),
                "targetFile": target_file,
                # 兼容既有 spec/产物字段；其语义一直是待填写目标文件，不是取数来源。
                "sourceFile": target_file,
                "placeholder": cell_at(row, columns["placeholder"]),
                "note": note,
                "needsConfirmation": "需确认" in note,
                "referenceFile": reference_file,
                "valueRequired": source_kind != "template",
                "sourceKind": source_kind,
                "aliases": [],
            }
        )
    if not specs:
        raise FactSpecImportError(f"清单未解析出任何字段: {path.name}")

    if output_path is not None:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(specs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return specs
