#!/usr/bin/env python3
"""从 manifest 运行商务标 Word 格式清洗。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from clean_docx import clean_docx
    from verify import verify_cleaned_docx
except ImportError:  # pragma: no cover
    from .clean_docx import clean_docx
    from .verify import verify_cleaned_docx


SCHEMA_VERSION = "bid-business-format-clean-v1"
REQUIRED_FIELDS = ("inputFile", "outlineFile", "outputFile", "projectName")


def run_manifest(manifest_path: str | Path, response: str = "summary") -> dict[str, Any]:
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest 必须是 JSON object")
    _validate_manifest(manifest)

    input_path = _resolve_manifest_path(manifest["inputFile"], path)
    outline_path = _resolve_manifest_path(manifest["outlineFile"], path)
    output_path = _resolve_manifest_path(manifest["outputFile"], path)
    style_path = _resolve_style_path(manifest.get("styleSpecPath"), path)
    report_path = output_path.with_name("business_format_clean_report.md")

    clean_result = clean_docx(
        input_file=input_path,
        outline_file=outline_path,
        output_file=output_path,
        project_name=str(manifest["projectName"]),
        style_spec_path=style_path,
    )
    report = verify_cleaned_docx(
        output_file=output_path,
        outline_file=outline_path,
        report_file=report_path,
        clean_result=clean_result,
        style_spec_path=style_path,
    )

    summary = {
        "outlineCount": report["outlineCount"],
        "matchedHeadingCount": report["matchedHeadingCount"],
        "unmatchedHeadingCount": len(report["unmatchedHeadings"]),
        "tocInserted": bool(clean_result["tocInserted"]),
        "tocPresent": bool(report["tocPresent"]),
        "headerCleaned": bool(report["headerCleaned"]),
        "insertedPageBreaks": int((clean_result.get("pagination") or {}).get("insertedPageBreaks", 0)),
        "removedBlankPageBreaks": int((clean_result.get("pagination") or {}).get("removedBlankPageBreaks", 0)),
        "fontFamilies": clean_result["fontFamilies"],
        "riskCount": len(report["formatRisks"]),
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "inputFile": str(input_path),
        "outlineFile": str(outline_path),
        "outputFile": str(output_path),
        "reportFile": str(report_path),
        "summary": summary,
    }
    if response != "summary":
        result["details"] = {
            "cleanResult": clean_result,
            "report": report,
            "styleSpecPath": str(style_path),
        }
    return result


def _validate_manifest(manifest: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_FIELDS if not manifest.get(field)]
    if missing:
        raise ValueError(f"manifest 缺少字段: {', '.join(missing)}")
    input_path = Path(manifest["inputFile"])
    output_path = Path(manifest["outputFile"])
    if input_path.resolve() == output_path.resolve():
        raise ValueError("inputFile 不得被覆盖，outputFile 必须不同于 inputFile")


def _resolve_style_path(style_path_value: Any, manifest_path: Path) -> Path:
    if style_path_value:
        return _resolve_manifest_path(style_path_value, manifest_path)
    return (Path(__file__).resolve().parents[1] / "references" / "business_heading_style.json").resolve()


def _resolve_manifest_path(value: Any, manifest_path: Path) -> Path:
    candidate = Path(str(value))
    if not candidate.is_absolute():
        candidate = (manifest_path.parent / candidate).resolve()
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 manifest 清洗商务标 Word 格式")
    parser.add_argument("manifest")
    parser.add_argument("--response", choices=("summary", "details"), default="summary")
    args = parser.parse_args(argv)

    result = run_manifest(args.manifest, response=args.response)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
