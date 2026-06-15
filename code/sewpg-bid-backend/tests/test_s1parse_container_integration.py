from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError:  # pragma: no cover - local lightweight fallback
    class _PytestMark:
        def integration(self, obj):
            return obj

        def skipif(self, *_args, **_kwargs):
            def decorator(obj):
                return obj

            return decorator

    class _PytestFallback:
        mark = _PytestMark()

    pytest = _PytestFallback()


COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


@unittest.skipUnless(os.getenv("BID_RUN_INTEGRATION") == "1", "requires running opencode container")
@pytest.mark.integration
@pytest.mark.skipif(os.getenv("BID_RUN_INTEGRATION") != "1", reason="requires running opencode container")
class S1ParseContainerIntegrationTests(unittest.TestCase):
    def test_business_manifest_routes_to_business_parse_runner_inside_opencode_container(self) -> None:
        container_script = r'''
import json
import subprocess
from pathlib import Path

root = Path("/tmp/s1parse-business-test")
root.mkdir(parents=True, exist_ok=True)
source_path = root / "business_tender.md"
text = """# Business tender
Project name: Container business project
Tender No: BUS-GEN-2026-001
Tenderer: Example Tenderer
Qualification requirements: bidder must be an independent legal person.
Bidder instructions table
| No | Name | Content |
| --- | --- | --- |
| 1 | Deadline | Submit before 2026-05-06 10:00 |
Commercial rejection: response is invalid if price exceeds ceiling.
Business scoring table
| No | Item | Score | Standard |
| 1 | Service plan | 2 | Best reasonable plan gets full score. |
"""
source_path.write_text(text, encoding="utf-8")
manifest_path = root / "manifest.json"
output_path = root / "s1_structured_result.json"
manifest = {
    "projectId": "PRJ-BUSINESS-CONTAINER",
    "bidType": "business",
    "parseProfile": "business",
    "structuredResultPath": str(output_path),
    "documents": [
        {
            "id": "DOC-1",
            "name": source_path.name,
            "sourcePath": str(source_path),
            "textPath": str(source_path),
        }
    ],
}
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

def run(*args):
    completed = subprocess.run(
        ["/usr/local/bin/s1parse", *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)

prepared = run(str(manifest_path))
submissions = {
    "projectBasics": [
        {"key": "projectName", "value": "Container business project", "evidenceIds": ["DOC-1:B000002"]},
        {"key": "tenderNo", "value": "BUS-GEN-2026-001", "evidenceIds": ["DOC-1:B000003"]},
        {"key": "tenderer", "value": "Example Tenderer", "evidenceIds": ["DOC-1:B000004"]},
    ],
    "qualificationRequirements": [
        {"content": "bidder must be an independent legal person", "evidenceIds": ["DOC-1:B000005"]}
    ],
    "bidderInstructions": [
        {"clauseNo": "1", "clauseName": "Deadline", "content": "Submit before 2026-05-06 10:00", "evidenceIds": ["DOC-1:T0001:R0002"]}
    ],
    "commercialRejectionClauses": [
        {"riskLevel": "high", "content": "response is invalid if price exceeds ceiling", "evidenceIds": ["DOC-1:B000008"]}
    ],
    "businessScoringCriteria": [
        {"scoringItem": "Service plan", "score": "2", "scoringStandard": "Best reasonable plan gets full score.", "evidenceIds": ["DOC-1:T0002:R0002"]}
    ],
    "projectDates": {"endDate": "2026-05-06 10:00", "evidenceIds": ["DOC-1:T0001:R0002"]},
}
for key, value in submissions.items():
    run("submit", str(manifest_path), key, json.dumps(value, ensure_ascii=False))
response = run("finalize", str(manifest_path))
payload = json.loads(output_path.read_text(encoding="utf-8"))
print(json.dumps({
    "prepared": prepared,
    "response": response,
    "schemaVersion": payload["structured"].get("schemaVersion"),
    "targetSkill": payload["structured"].get("targetSkill"),
    "workflow": payload["structured"].get("workflow"),
    "fieldGroupKeys": list(payload["structured"].get("fieldGroups", {}).keys()),
    "scoringCounts": {key: len(value or []) for key, value in (payload["structured"].get("scoringCriteria") or {}).items()},
    "projectFactFieldKeys": [item.get("key") for item in payload["structured"].get("projectFactFields") or []],
}, ensure_ascii=False))
'''.strip()

        completed = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_FILE),
                "exec",
                "-T",
                "opencode",
                "python3",
                "-c",
                container_script,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        payload = json.loads(completed.stdout.strip())
        response = payload["response"]

        self.assertEqual(payload["prepared"]["schemaVersion"], "bid-business-agentic-nav-v1")
        self.assertEqual(payload["prepared"]["stage"], "prepared")
        self.assertEqual(response["schemaVersion"], "bid-business-tender-structured-v1")
        self.assertEqual(response["targetSkill"], "bid-business-tender-structured-parser")
        self.assertEqual(payload["schemaVersion"], "bid-business-tender-structured-v1")
        self.assertEqual(payload["targetSkill"], "bid-business-tender-structured-parser")
        self.assertEqual(payload["workflow"]["mode"], "opencode-agentic-navigation")
        self.assertIn("projectBasics", payload["fieldGroupKeys"])
        self.assertIn("qualificationRequirements", payload["fieldGroupKeys"])
        self.assertIn("bidderInstructions", payload["fieldGroupKeys"])
        self.assertIn("commercialRejectionClauses", payload["fieldGroupKeys"])
        self.assertEqual(set(payload["scoringCounts"].keys()), {"business"})
        self.assertEqual(payload["scoringCounts"]["business"], 1)
        self.assertIn("projectName", payload["projectFactFieldKeys"])
        self.assertIn("tenderNo", payload["projectFactFieldKeys"])
