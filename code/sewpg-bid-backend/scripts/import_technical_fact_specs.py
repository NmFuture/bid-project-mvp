from __future__ import annotations

"""从《todo-技术标项目事实表清单》xlsx 生成技术标事实表字段 spec JSON。

用法：
    python scripts/import_technical_fact_specs.py <清单.xlsx> \
        [--output app/data/technical_fact_field_specs.json]

清单列（Sheet1，首行表头）：
    序号 / 来源文件 / 原占位符位置 / 实际要填写的字段 / 必要说明 / 复核 / 引用文件

生成的 spec 字段：
    seq, key, label, reviewLabel, sourceFile, placeholder, note,
    needsConfirmation, referenceFile, valueRequired, sourceKind, aliases
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any

import openpyxl

EXPECTED_HEADER = ["序号", "来源文件", "原占位符位置", "实际要填写的字段", "必要说明", "复核", "引用文件"]

# 引用文件 → 来源类别
SOURCE_KIND_RULES = [
    ("招标文件", "tender"),
    ("项目定制", "material"),
    ("认证证书", "cert"),
    ("平台输入", "platform"),
    ("自动生成", "derived"),
]


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


def import_specs(xlsx_path: Path) -> list[dict[str, Any]]:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise SystemExit(f"清单为空: {xlsx_path}")
    header = [cell_text(c) for c in rows[0]]
    if header[: len(EXPECTED_HEADER)] != EXPECTED_HEADER:
        raise SystemExit(f"表头不符，期望 {EXPECTED_HEADER}，实际 {header}")

    specs: list[dict[str, Any]] = []
    for row in rows[1:]:
        label = cell_text(row[3])
        if not label:
            continue
        note = cell_text(row[4])
        reference_file = cell_text(row[6])
        source_kind = classify_source(reference_file)
        specs.append(
            {
                "seq": int(row[0]),
                "key": normalize_key(label),
                "label": label,
                "reviewLabel": cell_text(row[5]),
                "sourceFile": cell_text(row[1]),
                "placeholder": cell_text(row[2]),
                "note": note,
                "needsConfirmation": "需确认" in note,
                "referenceFile": reference_file,
                "valueRequired": source_kind != "template",
                "sourceKind": source_kind,
                "aliases": [],
            }
        )
    return specs


def main() -> None:
    parser = argparse.ArgumentParser(description="导入技术标项目事实表字段清单为 spec JSON")
    parser.add_argument("xlsx", type=Path, help="todo-技术标项目事实表清单 xlsx 路径")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "app" / "data" / "technical_fact_field_specs.json",
        help="输出 JSON 路径（默认 app/data/technical_fact_field_specs.json）",
    )
    args = parser.parse_args()

    specs = import_specs(args.xlsx)
    fillable = sum(1 for s in specs if s["valueRequired"])
    needs_confirmation = sum(1 for s in specs if s["needsConfirmation"])
    template = sum(1 for s in specs if s["sourceKind"] == "template")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(specs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"已生成 {args.output}: 共 {len(specs)} 条，填值 {fillable} 条，"
        f"模板更新 {template} 条，需确认 {needs_confirmation} 条"
    )


if __name__ == "__main__":
    main()
