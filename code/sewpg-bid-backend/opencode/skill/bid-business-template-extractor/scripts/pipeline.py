from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from scripts.anchor_detector import detect_candidate_anchors, write_candidate_windows
from scripts.boundary_planner import plan_boundaries
from scripts.boundary_validator import validate_boundaries
from scripts.docx_blocks import extract_blocks
from scripts.docx_slicer import slice_docx_by_boundaries
from scripts.region_detector import detect_format_regions
from scripts.report_writer import write_review


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_pipeline(source_docx: Path, output_dir: Path) -> dict:
    source_docx = source_docx.resolve()
    output_dir = output_dir.resolve()
    if not source_docx.is_file():
        raise FileNotFoundError(f"找不到招标文件：{source_docx}")
    if output_dir.exists():
        for child in output_dir.iterdir():
            if child.name == ".gitkeep":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)

    blocks = extract_blocks(source_docx)
    regions = detect_format_regions(blocks)
    anchors = detect_candidate_anchors(blocks, regions)
    windows = write_candidate_windows(blocks, regions, anchors)
    draft_boundaries = plan_boundaries(blocks, regions, anchors)
    boundaries = validate_boundaries(blocks, regions, draft_boundaries)
    sliced_boundaries = slice_docx_by_boundaries(source_docx, blocks, boundaries, output_dir)
    boundaries = {"templates": sliced_boundaries["templates"]}

    write_json(output_dir / "blocks.json", blocks)
    write_json(output_dir / "regions.json", regions)
    write_json(output_dir / "candidate_anchors.json", anchors)
    write_json(output_dir / "candidate_windows.json", windows)
    write_json(output_dir / "boundaries.draft.json", draft_boundaries)
    write_json(output_dir / "boundaries.json", boundaries)
    write_review(output_dir, source_docx, regions, boundaries)

    return {
        "source": str(source_docx),
        "outputDir": str(output_dir),
        "summary": {
            "blockCount": len(blocks),
            "regionCount": len(regions),
            "anchorCount": len(anchors),
            "templateCount": len(boundaries["templates"]),
        },
    }
