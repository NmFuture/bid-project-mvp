from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class BusinessParseSkillScriptTests(unittest.TestCase):
    def test_business_skill_script_outputs_business_contract(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        script_path = (
            backend_root
            / "opencode"
            / "skill"
            / "bid-business-tender-structured-parser"
            / "scripts"
            / "run_from_manifest.py"
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "商务招标文件.md"
            source_path.write_text(
                "\n".join(
                    [
                        "# 商务招标文件",
                        "项目名称：华能甘肃100MW风电项目",
                        "招标编号：HN-BUS-2026-001",
                        "招标人：华能集团",
                        "附表3：商务评分标准表",
                        "| 序号 | 评分项 | 分值 | 得分点 | 证明材料要求 |",
                        "| --- | --- | --- | --- | --- |",
                        "| 1 | 企业业绩 | 20分 | 近三年同类风电项目业绩满足要求得满分。 | 提供合同或中标通知书。 |",
                        "投标函：按招标文件格式填写并签字盖章。",
                        "投标保证金：须提供电汇回单或保函。",
                        "投标人证明其是合格投标人并有资格履行合同的证明文件。",
                        "投标人须提供供货周期承诺书。",
                        "保密承诺书",
                        "投标人须提供保密承诺书。",
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
                        "projectId": "PRJ-BUSINESS-SKILL",
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
                [sys.executable, str(script_path), str(manifest_path)],
                check=True,
                capture_output=True,
                text=True,
            )

            summary = json.loads(completed.stdout)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            structured = payload["structured"]

            self.assertEqual(summary["schemaVersion"], "bid-business-tender-structured-v1")
            self.assertEqual(summary["targetSkill"], "bid-business-tender-structured-parser")
            self.assertEqual(structured["schemaVersion"], "bid-business-tender-structured-v1")
            self.assertEqual(structured["targetSkill"], "bid-business-tender-structured-parser")
            self.assertEqual(
                list(structured["fieldGroups"].keys()),
                ["projectBasics", "businessResponse", "qualificationSupport", "commitmentRequirements"],
            )
            self.assertEqual(set(structured["scoringCriteria"].keys()), {"business", "price", "compliance"})
            self.assertGreaterEqual(len(structured["scoringCriteria"]["business"]), 1)
            self.assertEqual(structured["scoringCriteria"]["business"][0]["scoringItem"], "企业业绩")
            self.assertEqual(len(structured["commitmentLetters"]), 3)
            self.assertEqual(structured["commitmentLetters"][0]["title"], "交货周期承诺书")
            self.assertEqual(structured["commitmentLetters"][1]["title"], "保密承诺书")
            self.assertEqual(structured["commitmentLetters"][2]["title"], "投标人不存在下列情形之一承诺函")
            self.assertEqual(len(structured.get("commitmentClues") or []), 0)
            self.assertEqual(next(field for field in structured["fieldGroups"]["commitmentRequirements"] if field["key"] == "generatedCommitmentCount")["value"], "3")
            fact_by_key = {field["fieldKey"]: field for field in structured["projectFactFields"]}
            self.assertEqual(fact_by_key["projectName"]["value"], "华能甘肃100MW风电项目")
            self.assertEqual(fact_by_key["tenderNo"]["value"], "HN-BUS-2026-001")
            self.assertEqual(fact_by_key["tenderer"]["value"], "华能集团")
            self.assertGreaterEqual(len(payload["items"]), 10)
