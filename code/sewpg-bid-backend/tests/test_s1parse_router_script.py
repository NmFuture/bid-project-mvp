from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class S1ParseRouterScriptTests(unittest.TestCase):
    def test_router_executes_technical_manifest(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        router_path = backend_root / "opencode" / "skill" / "s1parse_router.py"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "技术招标文件.md"
            source_path.write_text(
                "\n".join(
                    [
                        "# 招标文件",
                        "项目名称：测试技术项目",
                        "招标编号：TECH-2026-001",
                        "招标人：测试招标人",
                        "技术承诺：投标人应承诺满足全部技术规范。",
                    ]
                ),
                encoding="utf-8",
            )
            output_path = tmp_path / "s1_structured_result.json"
            manifest_path = tmp_path / "s1_parse_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "PRJ-TECH-ROUTER",
                        "bidType": "技术标",
                        "parseProfile": "technical",
                        "structuredResultPath": str(output_path),
                        "documents": [
                            {
                                "id": "DOC-1",
                                "name": source_path.name,
                                "sourcePath": str(source_path),
                                "textPath": str(source_path),
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(router_path), str(manifest_path)],
                check=True,
                capture_output=True,
                text=True,
            )

            summary = json.loads(completed.stdout)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

            self.assertEqual(summary["schemaVersion"], "bid-tender-structured-v1")
            self.assertEqual(payload["structured"]["schemaVersion"], "bid-tender-structured-v1")
            self.assertEqual(payload["structured"]["targetSkill"], "bid-tech-tender-structured-parser")

    def test_router_executes_business_manifest(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        router_path = backend_root / "opencode" / "skill" / "s1parse_router.py"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "商务招标文件.md"
            source_path.write_text(
                "\n".join(
                    [
                        "# 商务招标文件",
                        "项目名称：测试商务项目",
                        "招标编号：BUS-2026-001",
                        "招标人：测试招标人",
                        "附表3：商务评分标准表",
                        "| 序号 | 评分项 | 分值 | 得分点 | 证明材料要求 |",
                        "| --- | --- | --- | --- | --- |",
                        "| 1 | 企业业绩 | 20分 | 近三年同类项目业绩满足要求得满分。 | 提供合同或中标通知书。 |",
                        "投标保证金：须提交保函。",
                        "投标人应出具供货能力承诺函。",
                        "保密承诺书",
                        "投标人需提供保密承诺书。",
                        "投标人应提供保密承诺书。",
                        "发电量承诺书另附。",
                        "技术承诺：详见技术部分。",
                        "投标人不得存在下列情形之一。",
                        "投标人需要说明的其他内容。",
                    ]
                ),
                encoding="utf-8",
            )
            output_path = tmp_path / "s1_structured_result.json"
            manifest_path = tmp_path / "s1_parse_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "PRJ-BUSINESS-ROUTER",
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
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(router_path), str(manifest_path)],
                check=True,
                capture_output=True,
                text=True,
            )

            summary = json.loads(completed.stdout)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            structured = payload["structured"]

            self.assertEqual(summary["schemaVersion"], "bid-business-tender-structured-v1")
            self.assertEqual(structured["schemaVersion"], "bid-business-tender-structured-v1")
            self.assertEqual(structured["targetSkill"], "bid-business-tender-structured-parser")
            field_group_keys = list(structured["fieldGroups"].keys())
            self.assertIn("projectBasics", field_group_keys)
            self.assertIn("businessResponse", field_group_keys)
            self.assertIn("qualificationSupport", field_group_keys)
            self.assertIn("commitmentRequirements", field_group_keys)
            self.assertIn("qualificationRequirements", field_group_keys)
            self.assertIn("bidderInstructions", field_group_keys)
            self.assertIn("commercialRejectionClauses", field_group_keys)
            self.assertEqual(len(structured["commitmentLetters"]), 3)
            self.assertEqual(structured["commitmentLetters"][0]["title"], "供货能力承诺函")
            self.assertEqual(structured["commitmentLetters"][1]["title"], "保密承诺书")
            self.assertEqual(structured["commitmentLetters"][2]["title"], "投标人不存在下列情形之一承诺函")
            self.assertEqual(len(structured.get("commitmentClues") or []), 0)
