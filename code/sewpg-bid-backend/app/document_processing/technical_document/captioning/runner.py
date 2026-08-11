"""技术标图表题注编号的 manifest 入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .captions import number_captions


# 题注字体/字号/行距与正文组装、格式清洗共用同一份契约
DEFAULT_STYLE_SPEC = Path(__file__).resolve().parents[1] / "resources" / "heading_style.json"

SCHEMA_VERSION = "bid-tech-caption-number-v1"
REQUIRED_FIELDS = ("inputFile", "outputFile")


def _resolve_manifest_path(value: Any, manifest_path: Path) -> Path:
    path = Path(str(value or "")).expanduser()
    if not path.is_absolute():
        path = (manifest_path.parent / path).resolve()
    return path


def _caption_style_from_spec(style_spec_path: Path | None) -> dict[str, Any]:
    """题注字体/字号/行距取 `heading_style.json` 的 `caption` 段，不另立一套默认值。"""
    if not style_spec_path or not style_spec_path.exists():
        return {}
    try:
        spec = json.loads(style_spec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    caption = spec.get("caption") if isinstance(spec, dict) else None
    if not isinstance(caption, dict):
        return {}
    config: dict[str, Any] = {
        "new_caption_font": {
            "eastasia": str(caption.get("zh_font") or "等线"),
            "ascii": str(caption.get("en_font") or "等线"),
            "size_pt": float(caption.get("size_pt") or 12.0),
        }
    }
    if caption.get("line_spacing"):
        config["caption_line_spacing"] = float(caption["line_spacing"])
    return config


def run_manifest(manifest_path: str | Path, response: str = "summary") -> dict[str, Any]:
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    missing = [field for field in REQUIRED_FIELDS if not str(manifest.get(field) or "").strip()]
    if missing:
        raise ValueError(f"manifest 缺少必填字段：{'、'.join(missing)}")

    input_path = _resolve_manifest_path(manifest["inputFile"], path)
    output_path = _resolve_manifest_path(manifest["outputFile"], path)
    style_spec_path = (
        _resolve_manifest_path(manifest["styleSpecPath"], path)
        if str(manifest.get("styleSpecPath") or "").strip()
        else DEFAULT_STYLE_SPEC
    )

    config = _caption_style_from_spec(style_spec_path)
    if manifest.get("highlight") is not None:
        config["highlight"] = bool(manifest["highlight"])
    if manifest.get("useWordFields") is not None:
        config["use_word_fields"] = bool(manifest["useWordFields"])
    if manifest.get("unifyCaptionFormat") is not None:
        config["unify_caption_format"] = bool(manifest["unifyCaptionFormat"])
    if isinstance(manifest.get("configOverrides"), dict):
        config.update(manifest["configOverrides"])

    result = number_captions(input_path, output_path, config)
    summary = dict(result["summary"])
    warnings = list(result["warnings"])
    # 一条题注都没加时不留半成品文件，调用方沿用上一环节产物
    status = "completed" if summary["captionCount"] else "skipped"
    if status == "skipped":
        output_path.unlink(missing_ok=True)

    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "inputFile": str(input_path),
        "outputFile": str(output_path) if status == "completed" else "",
        "summary": {**summary, "warnings": warnings},
        "warnings": warnings,
    }
    if response == "full":
        payload["records"] = result["records"]
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="技术标图表题注编号")
    parser.add_argument("manifest", help="manifest JSON 路径")
    parser.add_argument("--response", default="summary", choices=["summary", "full"],
                        help="summary 只回摘要；full 附带逐条题注记录")
    args = parser.parse_args()
    payload = run_manifest(args.manifest, args.response)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
