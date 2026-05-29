from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

CURRENT = Path(__file__).resolve()
SCRIPT_DIR = CURRENT.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from business_contract import SCHEMA_VERSION, SKILL_NAME, build_business_result


def _summary(result: dict[str, Any], output_path: Path) -> dict[str, Any]:
    structured = result.get("structured") if isinstance(result.get("structured"), dict) else {}
    scoring = structured.get("scoringCriteria") if isinstance(structured.get("scoringCriteria"), dict) else {}
    project_dates = structured.get("projectDates") if isinstance(structured.get("projectDates"), dict) else {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "targetSkill": SKILL_NAME,
        "outputFile": str(output_path),
        "summary": {
            "itemCount": len(result.get("items") or []),
            "categoryCounts": structured.get("categoryCounts") or {},
            "scoringCounts": {
                key: len(scoring.get(key) or [])
                for key in ("business", "price", "compliance")
            },
            "projectDates": {
                "startDate": project_dates.get("startDate") or "",
                "endDate": project_dates.get("endDate") or "",
            },
        },
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: s1parse <manifest>", file=sys.stderr)
        return 64

    manifest_path = Path(sys.argv[1])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_path = Path(str(manifest.get("structuredResultPath") or manifest_path.with_name("s1_structured_result.json")))
    result = build_business_result(manifest, mode="opencode-skill")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(_summary(result, output_path), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
