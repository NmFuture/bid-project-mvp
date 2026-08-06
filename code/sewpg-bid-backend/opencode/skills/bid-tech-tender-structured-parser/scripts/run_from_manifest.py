from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

CURRENT = Path(__file__).resolve()
SCRIPT_DIR = CURRENT.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from agentic.run_agentic import main
from parser_core import SKILL_NAME, parse_manifest


AGENTIC_COMMANDS = {
    "prepare",
    "overview",
    "search",
    "checklist",
    "read",
    "table",
    "window",
    "submit",
    "status",
    "validate",
    "finalize",
}


def _summary(result: dict[str, Any], output_path: Path) -> dict[str, Any]:
    structured = result.get("structured") if isinstance(result.get("structured"), dict) else {}
    scoring = structured.get("scoringCriteria") if isinstance(structured.get("scoringCriteria"), dict) else {}
    project_dates = structured.get("projectDates") if isinstance(structured.get("projectDates"), dict) else {}
    return {
        "schemaVersion": "bid-tender-structured-v1",
        "targetSkill": SKILL_NAME,
        "outputFile": str(output_path),
        "summary": {
            "itemCount": len(result.get("items") or []),
            "categoryCounts": structured.get("categoryCounts") or {},
            "scoringCounts": {
                key: len(scoring.get(key) or [])
                for key in ("technical", "business", "price", "lcoe", "compliance")
            },
            "projectDates": {
                "startDate": project_dates.get("startDate") or "",
                "endDate": project_dates.get("endDate") or "",
            },
        },
    }


def _run_legacy_manifest(manifest_path: Path) -> int:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    output_path = Path(str(manifest.get("structuredResultPath") or manifest_path.with_name("s1_structured_result.json")))
    result = parse_manifest(manifest, mode="opencode-skill")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(_summary(result, output_path), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 1 and args[0].strip().lower() not in AGENTIC_COMMANDS:
        raise SystemExit(_run_legacy_manifest(Path(args[0]).expanduser().resolve()))
    raise SystemExit(main(args))
