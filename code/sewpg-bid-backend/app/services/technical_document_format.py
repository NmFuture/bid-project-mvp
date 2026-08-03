from __future__ import annotations

import copy
import json
import math
import shutil
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.font_policy import normalize_font_style_overrides
from app.services.onlyoffice_documents import document_path
from app.services.workspace_project_access import get_workspace_project_runtime_state
from app.services.workspace_artifacts import technical_workspace_stage_dir


TECH_FORMAT_PRESETS = {
    "standard": {
        "label": "标准技术标格式",
        "description": "默认技术标版式：标题、正文、表格、目录、页眉和分页统一规范化。",
    },
    "custom": {
        "label": "自定义格式",
        "description": "按用户设置的字体、字号、行距、页边距、目录和页眉规则执行格式规范化。",
    },
}


def apply_technical_document_format_preset(
    project_id: str,
    preset: str = "standard",
    style_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project = get_workspace_project_runtime_state(
        project_id,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=KeyError,
        wrong_type_error=lambda _project_id: ValueError("技术标格式切换仅支持技术标项目。"),
    )

    preset_key = preset if preset in TECH_FORMAT_PRESETS else "standard"
    preset_info = TECH_FORMAT_PRESETS[preset_key]
    normalized_overrides = normalize_font_style_overrides(style_overrides)
    source_path = document_path(project_id)
    if not source_path.exists():
        state = copy.deepcopy(project.get("document_state") if isinstance(project.get("document_state"), dict) else {})
        raise FileNotFoundError(f"技术标正文文件不存在：{state.get('fileName') or source_path.name}")

    from app.services.tech_assembly import (
        _prepare_tech_format_outline,
        _prepare_toc_json as _prepare_technical_toc_json,
        _run_local_tech_format_cleaner,
    )

    outline_state = copy.deepcopy(project.get("outline_state") if isinstance(project.get("outline_state"), dict) else {})
    parse_storage = copy.deepcopy(project.get("parse_storage") if isinstance(project.get("parse_storage"), dict) else {})
    work_dir = technical_workspace_stage_dir(project_id, "s5_format_switch_workdir")
    work_dir.mkdir(parents=True, exist_ok=True)
    toc_json_path = _prepare_technical_toc_json(project_id, project, outline_state, parse_storage, work_dir)
    outline_path = _prepare_tech_format_outline(toc_json_path, work_dir)
    output_path = work_dir / f"{source_path.stem}.{preset_key}.formatted.docx"
    manifest_path = work_dir / f"tech_format_{preset_key}_input.json"
    style_spec_path = _prepare_technical_format_style_spec(preset_key, normalized_overrides, work_dir)
    manifest = {
        "schemaVersion": "bid-tech-format-clean-manifest-v1",
        "inputFile": str(source_path),
        "outlineFile": str(outline_path),
        "outputFile": str(output_path),
        "projectName": str(project.get("name") or project_id),
        "formatPreset": preset_key,
        "styleSpecPath": str(style_spec_path),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    result = _run_local_tech_format_cleaner(manifest_path)
    formatted_path = Path(str(result.get("outputFile") or output_path)).expanduser()
    if not formatted_path.exists():
        raise RuntimeError(f"技术标格式切换未生成输出文件：{formatted_path}")
    shutil.copy2(formatted_path, source_path)
    return {
        "preset": preset_key,
        "label": preset_info["label"],
        "description": preset_info["description"],
        "styleOverrides": copy.deepcopy(normalized_overrides) if preset_key == "custom" else {},
        "manifestPath": str(manifest_path),
        "outputFile": str(formatted_path),
        "summary": result.get("summary") if isinstance(result.get("summary"), dict) else {},
    }


def _prepare_technical_format_style_spec(
    preset_key: str,
    style_overrides: dict[str, Any],
    work_dir: Path,
) -> Path:
    base_path = BASE_DIR / "opencode" / "skills" / "bid-tech-assembler" / "references" / "heading_style.json"
    spec = json.loads(base_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError("技术标格式规范配置不是 JSON object。")
    spec = copy.deepcopy(spec)
    if preset_key == "custom":
        _apply_technical_style_overrides(spec, style_overrides)
    style_path = work_dir / f"tech_format_{preset_key}_style.json"
    style_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return style_path


def _apply_technical_style_overrides(spec: dict[str, Any], overrides: dict[str, Any]) -> None:
    def text_value(key: str, default: str = "") -> str:
        raw_value = overrides.get(key)
        if not isinstance(raw_value, str):
            return default
        value = raw_value.strip()
        return value or default

    def number_value(key: str, min_value: float, max_value: float) -> float | None:
        if key not in overrides or overrides.get(key) in (None, ""):
            return None
        raw_value = overrides.get(key)
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            return None
        value = float(raw_value)
        if not math.isfinite(value) or not min_value <= value <= max_value:
            return None
        return value

    def bool_value(key: str) -> bool | None:
        if key not in overrides or not isinstance(overrides.get(key), bool):
            return None
        return overrides[key]

    body = spec.setdefault("body", {})
    if text_value("bodyZhFont"):
        body["zh_font"] = text_value("bodyZhFont")
    if text_value("bodyEnFont"):
        body["en_font"] = text_value("bodyEnFont")
    if (value := number_value("bodySizePt", 8, 22)) is not None:
        body["size_pt"] = value
    if (value := number_value("bodyLineSpacing", 1, 3)) is not None:
        body["line_spacing"] = value
    if (value := number_value("bodyFirstLineIndentChars", 0, 4)) is not None:
        body["first_line_indent_chars"] = value

    table = spec.setdefault("table_cell", {})
    if text_value("tableZhFont"):
        table["zh_font"] = text_value("tableZhFont")
    if text_value("tableEnFont"):
        table["en_font"] = text_value("tableEnFont")
    if (value := number_value("tableSizePt", 8, 16)) is not None:
        table["size_pt"] = value
    if (value := number_value("tableLineSpacing", 1, 2)) is not None:
        table["line_spacing"] = value

    page = spec.setdefault("page", {})
    for source_key, target_key in (
        ("pageTopCm", "top_cm"),
        ("pageBottomCm", "bottom_cm"),
        ("pageLeftCm", "left_cm"),
        ("pageRightCm", "right_cm"),
    ):
        if (value := number_value(source_key, 0.5, 6)) is not None:
            page[target_key] = value

    heading = spec.setdefault("heading", {})
    for level in range(1, 7):
        level_cfg = heading.setdefault(str(level), {})
        prefix = f"heading{level}"
        if text_value(f"{prefix}ZhFont"):
            level_cfg["zh_font"] = text_value(f"{prefix}ZhFont")
        if text_value(f"{prefix}EnFont"):
            level_cfg["en_font"] = text_value(f"{prefix}EnFont")
        if (value := number_value(f"{prefix}SizePt", 8, 26)) is not None:
            level_cfg["size_pt"] = value
        if (value := number_value(f"{prefix}LineSpacing", 1, 3)) is not None:
            level_cfg["line_spacing"] = value
        if (value := bool_value(f"{prefix}Bold")) is not None:
            level_cfg["bold"] = value
        align = text_value(f"{prefix}Align")
        if align in {"left", "center", "right", "both"}:
            level_cfg["align"] = align

    toc = spec.setdefault("toc", {})
    if (value := bool_value("insertToc")) is not None:
        toc["insert_when_missing"] = value
    if (value := bool_value("tocPageBreakAfter")) is not None:
        toc["page_break_after"] = value

    header = spec.setdefault("header", {})
    if text_value("headerTextTemplate"):
        header["text_template"] = text_value("headerTextTemplate")
    if text_value("headerZhFont"):
        header["zh_font"] = text_value("headerZhFont")
    if (value := number_value("headerSizePt", 6, 14)) is not None:
        header["size_pt"] = value
