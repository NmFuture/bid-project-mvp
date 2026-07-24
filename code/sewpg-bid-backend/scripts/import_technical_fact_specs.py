from __future__ import annotations

"""从《todo-技术标项目事实表清单》xlsx 生成技术标事实表字段 spec JSON。

解析核心在 app/services/technical_fact_spec_import.py（设置页上传接口共用），
本脚本只是 CLI 薄 wrapper。

用法：
    python scripts/import_technical_fact_specs.py <清单.xlsx> \
        [--output app/data/technical_fact_field_specs.json]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.technical_fact_spec_import import FactSpecImportError, import_specs


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

    try:
        specs = import_specs(args.xlsx, output_path=args.output)
    except FactSpecImportError as exc:
        raise SystemExit(str(exc)) from exc
    fillable = sum(1 for s in specs if s["valueRequired"])
    needs_confirmation = sum(1 for s in specs if s["needsConfirmation"])
    template = sum(1 for s in specs if s["sourceKind"] == "template")

    print(
        f"已生成 {args.output}: 共 {len(specs)} 条，填值 {fillable} 条，"
        f"模板更新 {template} 条，需确认 {needs_confirmation} 条"
    )


if __name__ == "__main__":
    main()
