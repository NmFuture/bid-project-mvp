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
        container_script = '''
import json
import subprocess
from pathlib import Path

root = Path("/tmp/s1parse-business-test")
root.mkdir(parents=True, exist_ok=True)
source_path = root / "商务招标文件.md"
text = """# 商务招标文件
项目名称：脱敏风电设备采购项目
招标编号：BUS-GEN-2026-001
招标人：示例招标单位
附表3：商务评分标准表
| 序号 | 评分项 | 分值 | 得分点 | 证明材料要求 |
| --- | --- | --- | --- | --- |
| 1 | 企业业绩 | 20分 | 近三年同类风电项目业绩满足要求得满分。 | 提供合同或中标通知书。 |
投标函：按招标文件格式填写并签字盖章。
投标保证金：须提供电汇回单或保函。
投标人证明其是合格投标人并有资格履行合同的证明文件。
投标人不得存在下列情形之一。
投标人需要说明的其他内容。
"""
source_path.write_text(text, encoding="utf-8")
manifest_path = root / "manifest.json"
output_path = root / "s1_structured_result.json"
manifest = {
    "projectId": "PRJ-BUSINESS-CONTAINER",
    "bidType": "商务标",
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
completed = subprocess.run(
    ["/usr/local/bin/s1parse", "offline-fallback", str(manifest_path)],
    check=True,
    capture_output=True,
    text=True,
    encoding="utf-8",
)
response = json.loads(completed.stdout)
payload = json.loads(output_path.read_text(encoding="utf-8"))
print(json.dumps({
    "response": response,
    "schemaVersion": payload["structured"].get("schemaVersion"),
    "targetSkill": payload["structured"].get("targetSkill"),
    "fieldGroupKeys": list(payload["structured"].get("fieldGroups", {}).keys()),
    "scoringCounts": {key: len(value or []) for key, value in (payload["structured"].get("scoringCriteria") or {}).items()},
    "commitmentLetterCount": len(payload["structured"].get("commitmentLetters") or []),
    "projectFactFieldKeys": [item.get("fieldKey") for item in payload["structured"].get("projectFactFields") or []],
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

        self.assertEqual(response["schemaVersion"], "bid-business-tender-structured-v1")
        self.assertEqual(response["targetSkill"], "bid-business-tender-structured-parser")
        self.assertEqual(payload["schemaVersion"], "bid-business-tender-structured-v1")
        self.assertEqual(payload["targetSkill"], "bid-business-tender-structured-parser")
        self.assertIn("projectBasics", payload["fieldGroupKeys"])
        self.assertIn("qualificationRequirements", payload["fieldGroupKeys"])
        self.assertIn("bidderInstructions", payload["fieldGroupKeys"])
        self.assertIn("commercialRejectionClauses", payload["fieldGroupKeys"])
        self.assertEqual(set(payload["scoringCounts"].keys()), {"business"})
        self.assertGreaterEqual(payload["scoringCounts"]["business"], 1)
        self.assertEqual(payload["commitmentLetterCount"], 0)
        self.assertIn("projectName", payload["projectFactFieldKeys"])
        self.assertIn("tenderNo", payload["projectFactFieldKeys"])
