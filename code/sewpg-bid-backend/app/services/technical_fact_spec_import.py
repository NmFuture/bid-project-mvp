from __future__ import annotations

"""技术标项目事实表字段清单 xlsx → spec JSON 的解析核心。

Docker 部署只 COPY app/，scripts/ 不是运行时可依赖的包路径，因此解析逻辑放在
app 包内：设置页上传接口（app/api/routes/settings.py）与
scripts/import_technical_fact_specs.py CLI 共用本模块。

清单列（Sheet1，首行表头）：
    序号 / 待填写文件 / 原占位符位置 / 实际要填写的字段 / 必要说明 / 复核 / 来源文件

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

HEADER_LAYOUTS = {
    tuple(EXPECTED_HEADER): {"target_file": 1, "reference_file": 6},
    tuple(LEGACY_HEADER): {"target_file": 1, "reference_file": 6},
}

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
    ref = (reference_file or "").strip()
    if not ref or ref == "/":
        return "template"
    for prefix, kind in SOURCE_KIND_RULES:
        if ref.startswith(prefix):
            return kind
    return "material"


def cell_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


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
    header_key = tuple(header[: len(EXPECTED_HEADER)])
    layout = HEADER_LAYOUTS.get(header_key)
    if layout is None:
        raise FactSpecImportError(
            f"表头不符，期望 {EXPECTED_HEADER}（兼容历史表头 {LEGACY_HEADER}），实际 {header}"
        )

    specs: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows[1:], start=2):
        label = cell_text(row[3])
        if not label:
            continue
        note = cell_text(row[4])
        target_file = cell_text(row[layout["target_file"]])
        reference_file = cell_text(row[layout["reference_file"]])
        source_kind = classify_source(reference_file)
        try:
            seq = int(row[0])
        except (TypeError, ValueError) as exc:
            raise FactSpecImportError(f"第 {row_index} 行序号无效：{row[0]!r}") from exc
        specs.append(
            {
                "seq": seq,
                "key": normalize_key(label),
                "label": label,
                "reviewLabel": cell_text(row[5]),
                "targetFile": target_file,
                # 兼容既有 spec/产物字段；其语义一直是待填写目标文件，不是取数来源。
                "sourceFile": target_file,
                "placeholder": cell_text(row[2]),
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
