#!/usr/bin/env python3
"""按 manifest 给技术标成稿的评分索引表建立交叉引用与页码。

后端在「正文组装 → 格式清洗」之后调用本脚本；文档里没有评分索引表时返回
status=skipped，不抛错、不阻断出稿。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

if __package__:
    from . import xref as xref_module  # type: ignore[no-redef]
else:  # 直接以脚本方式运行/被 importlib 加载
    _spec = importlib.util.spec_from_file_location("bid_tech_score_index_xref_core", SCRIPT_DIR / "xref.py")
    if _spec is None or _spec.loader is None:  # pragma: no cover - 环境异常
        raise ImportError("无法加载 xref.py")
    xref_module = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = xref_module
    _spec.loader.exec_module(xref_module)


SCHEMA_VERSION = "bid-tech-score-index-xref-v1"
REQUIRED_FIELDS = ("inputFile", "outputFile")


def run_manifest(manifest_path: str | Path, response: str = "summary") -> dict[str, Any]:
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    missing = [field for field in REQUIRED_FIELDS if not manifest.get(field)]
    if missing:
        raise ValueError(f"manifest missing fields: {', '.join(missing)}")

    input_path = _resolve(manifest["inputFile"], path)
    output_path = _resolve(manifest["outputFile"], path)
    if input_path.resolve() == output_path.resolve():
        raise ValueError("inputFile must not equal outputFile")
    if not input_path.exists():
        raise FileNotFoundError(f"inputFile does not exist: {input_path}")

    mapping = _load_mapping(manifest, path)
    index_headers = _string_list(manifest.get("indexHeaders")) or None
    factor_headers = _string_list(manifest.get("factorHeaders")) or None

    try:
        report = xref_module.build_xref(
            str(input_path),
            str(output_path),
            mapping=mapping,
            index_headers=index_headers,
            factor_headers=factor_headers,
            overwrite=bool(manifest.get("overwrite")),
            sync_title=bool(manifest.get("syncTitle")),
            styled_link=bool(manifest.get("styledLink")),
            dry_run=bool(manifest.get("dryRun")),
            use_word=bool(manifest.get("updateFieldsWithWord")),
        )
    except xref_module.IndexTableNotFound as exc:
        return _skipped_result(input_path, output_path, "index_table_not_found", str(exc))
    except xref_module.MappingUnresolved as exc:
        return _skipped_result(input_path, output_path, "mapping_unresolved", str(exc))

    verify: dict[str, Any] = {}
    if not report["dryRun"]:
        verify = xref_module.verify_xref(str(output_path), index_headers, factor_headers)

    summary = {
        "tableFound": True,
        "headingCount": int(report["headingCount"]),
        "rowCount": int(report["rowCount"]),
        "entryCount": int(report["entryCount"]),
        "linkedCount": len(report["linked"]),
        "mismatchCount": len(report["mismatch"]),
        "unresolvedCount": len(report["unresolved"]),
        "filledRowCount": len((report["fill"] or {}).get("filled") or []),
        "bookmarksCreated": int(report["bookmarksCreated"]),
        "pageNumbersResolved": bool(report["pageNumbersResolved"]),
        "hyperlinkCount": int(verify.get("hyperlinkCount") or 0),
        "pagerefCount": int(verify.get("pagerefCount") or 0),
        "bookmarksResolvable": bool(verify.get("bookmarksResolvable", True)),
        "tocConflictCount": len(verify.get("tocConflicts") or []),
        "danglingRelationshipCount": int(verify.get("danglingRelationshipCount") or 0),
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "inputFile": str(input_path),
        "outputFile": report["outputFile"],
        "summary": summary,
        "warnings": _build_warnings(report, verify),
    }
    if response != "summary":
        result["details"] = {"build": report, "verify": verify}
    return result


def _skipped_result(input_path: Path, output_path: Path, code: str, message: str) -> dict[str, Any]:
    """跳过时输出文件不产生，调用方沿用上一环节的成稿。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "skipped",
        "inputFile": str(input_path),
        "outputFile": "",
        "summary": {"tableFound": code != "index_table_not_found", "linkedCount": 0},
        "warnings": [{"code": code, "message": message, "count": 1}],
    }


def _build_warnings(report: dict[str, Any], verify: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []

    def add(code: str, message: str, count: int) -> None:
        if count > 0:
            warnings.append({"code": code, "message": message, "count": count})

    add(
        "xref_unresolved_entry",
        "索引表中存在无法定位到正文章节的条目，已保持原样，需人工处理。",
        len(report["unresolved"]),
    )
    add(
        "xref_title_mismatch",
        "索引表文字与正文标题不一致，已按章节号建立引用，建议核对。",
        len(report["mismatch"]),
    )
    add(
        "xref_no_entry",
        "索引表的章节索引列为空，未建立任何交叉引用。",
        1 if report["entryCount"] == 0 else 0,
    )
    fill = report["fill"] or {}
    add(
        "xref_factor_not_in_mapping",
        "映射里缺少对应评审因素，这些行未填写章节索引。",
        len(fill.get("nokey") or []),
    )
    if not report["pageNumbersResolved"] and report["entryCount"]:
        add("xref_page_number_pending", "页码为占位符，需在 Word/WPS 中全选后按 F9 刷新域。", 1)
    if verify:
        add(
            "xref_bookmark_missing",
            "存在无法解析的书签引用，请检查成品。",
            len(verify.get("missingBookmarks") or []),
        )
        add(
            "xref_toc_page_conflict",
            "索引表页码与目录页码不一致，请核对。",
            len(verify.get("tocConflicts") or []),
        )
        add(
            "xref_dangling_relationship",
            "成品存在失效的关系引用，请检查图片等资源。",
            int(verify.get("danglingRelationshipCount") or 0),
        )
    return warnings


def _load_mapping(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any] | None:
    inline = manifest.get("mapping")
    if isinstance(inline, dict) and inline:
        return inline
    mapping_file = manifest.get("mappingFile")
    if not mapping_file:
        return None
    path = _resolve(mapping_file, manifest_path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("mappingFile must be a JSON object")
    return data or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _resolve(value: Any, manifest_path: Path) -> Path:
    candidate = Path(str(value))
    if not candidate.is_absolute():
        candidate = (manifest_path.parent / candidate).resolve()
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run technical bid score-index cross-reference from manifest")
    parser.add_argument("manifest")
    parser.add_argument("--response", choices=("summary", "details"), default="summary")
    args = parser.parse_args(argv)
    print(json.dumps(run_manifest(args.manifest, response=args.response), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
