#!/usr/bin/env python3
"""Fill a requested technical bid table/Word placeholder from manifest data."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from docx import Document


SCHEMA_VERSION = "bid-tech-table-fill-v1"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("manifest must be a JSON object")
    return data


def run_from_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    output_file = Path(str(manifest.get("outputFile") or manifest_path.with_name("AI填写.docx")))
    output_file.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()
    doc.add_heading(str(manifest.get("title") or "AI 填写产物"), level=1)
    doc.add_paragraph("本文件由 bid-tech-table-filler 根据人工指定参考素材和招标解析字段生成。")
    doc.add_paragraph(f"缺口项：{manifest.get('gapId') or ''}")
    turbine = manifest.get("projectTurbineModel") if isinstance(manifest.get("projectTurbineModel"), dict) else {}
    if turbine.get("model"):
        turbine_parts = [
            str(turbine.get("model") or ""),
            str(turbine.get("platform") or ""),
            f"{turbine.get('ratedPowerKw')}kW" if turbine.get("ratedPowerKw") else "",
            f"叶轮{turbine.get('rotorDiameterM')}m" if turbine.get("rotorDiameterM") else "",
        ]
        doc.add_paragraph(f"投标机型：{' / '.join(part for part in turbine_parts if part)}")
    refs = manifest.get("referenceMaterialIds") if isinstance(manifest.get("referenceMaterialIds"), list) else []
    fields = manifest.get("parseFieldIds") if isinstance(manifest.get("parseFieldIds"), list) else []
    doc.add_paragraph(f"参考素材：{', '.join(str(item) for item in refs) if refs else '未指定'}")
    doc.add_paragraph(f"解析字段：{', '.join(str(item) for item in fields) if fields else '未指定'}")
    doc.add_paragraph("【待人工核验：所有自动填写内容需结合原始证明材料复核】")
    doc.save(output_file)

    unfilled_fields = [] if refs and fields else ["参考素材或解析字段不足，需人工复核"]
    return {
        "schema_version": SCHEMA_VERSION,
        "outputFile": str(output_file),
        "unfilledFields": unfilled_fields,
        "evidenceRefs": [
            {"type": "material", "id": str(item)}
            for item in refs
        ] + [
            {"type": "parse_field", "id": str(item)}
            for item in fields
        ],
        "filledAt": now_iso(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--response", choices=("summary", "full"), default="summary")
    args = parser.parse_args()
    result = run_from_manifest(Path(args.manifest))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
