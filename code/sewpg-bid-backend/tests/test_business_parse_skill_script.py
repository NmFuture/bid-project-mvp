from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from docx import Document


def field_by_key(fields: list[dict], key: str) -> dict:
    return next(field for field in fields if field["key"] == key)


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
            source_path = tmp_path / "商务招标文件.docx"
            doc = Document()
            doc.add_paragraph("华能甘肃100MW风电项目")
            cover_table = doc.add_table(rows=3, cols=3)
            cover_table.cell(0, 0).text = "招标人"
            cover_table.cell(0, 1).text = "："
            cover_table.cell(0, 2).text = "华能集团"
            cover_table.cell(1, 0).text = "项目单位"
            cover_table.cell(1, 1).text = "："
            cover_table.cell(1, 2).text = "华能甘肃公司"
            cover_table.cell(2, 0).text = "招标代理机构"
            cover_table.cell(2, 1).text = "："
            cover_table.cell(2, 2).text = "睿采数动公司"
            doc.add_paragraph("招标编号：HN-BUS-2026-001")
            doc.add_paragraph("投标人须知前附表")
            instruction_table = doc.add_table(rows=5, cols=3)
            for col, text in enumerate(["条款号", "条款名称", "编列内容"]):
                instruction_table.cell(0, col).text = text
            instruction_rows = [
                ("1.1.2", "招标人", "招标人：华能集团 地 址：北京市西城区复兴门内大街6号 联 系 人：李先生 电 话：010-81917899"),
                ("1.1.3", "招标代理机构", "招标代理机构：睿采数动公司 地址：北京市昌平区北七家镇七北路10号 联系人：梁先生 电话：400-010-1086"),
                ("1.1.4", "招标项目名称", "华能甘肃100MW风电项目"),
                ("4.2.1", "投标截止时间", "2026年1月26日09时00分"),
            ]
            for row_index, values in enumerate(instruction_rows, start=1):
                for col, text in enumerate(values):
                    instruction_table.cell(row_index, col).text = text
            doc.add_paragraph("附表1：符合性审查标准表")
            compliance_table = doc.add_table(rows=2, cols=3)
            for col, text in enumerate(["序号", "审查项目", "审查标准"]):
                compliance_table.cell(0, col).text = text
            for col, text in enumerate(["1", "投标保证金", "按照招标文件要求提供投标保证金且无瑕疵。"]):
                compliance_table.cell(1, col).text = text
            doc.add_paragraph("附表3：商务评分标准表")
            business_table = doc.add_table(rows=2, cols=5)
            for col, text in enumerate(["序号", "评分项", "分值", "得分点", "证明材料要求"]):
                business_table.cell(0, col).text = text
            for col, text in enumerate(["1", "企业业绩", "20分", "近三年同类风电项目业绩满足要求得满分。", "提供合同或中标通知书。"]):
                business_table.cell(1, col).text = text
            doc.add_paragraph("附表4：投标报价评分标准")
            price_table = doc.add_table(rows=2, cols=4)
            for col, text in enumerate(["序号", "评分项", "分值", "得分点"]):
                price_table.cell(0, col).text = text
            for col, text in enumerate(["1", "评标价", "100分", "评标价等于评标基准价时得100分。"]):
                price_table.cell(1, col).text = text
            doc.add_paragraph("投标函：按招标文件格式填写并签字盖章。")
            doc.add_paragraph("投标保证金：须提供电汇回单或保函。")
            doc.add_paragraph("投标人证明其是合格投标人并有资格履行合同的证明文件。")
            doc.add_paragraph("投标人须提供供货周期承诺书。")
            doc.add_paragraph("保密承诺书")
            doc.add_paragraph("投标人须提供保密承诺书。")
            doc.add_paragraph("投标人应提供保密承诺书。")
            doc.add_paragraph("发电量承诺书另附。")
            doc.add_paragraph("技术承诺：详见技术部分。")
            doc.add_paragraph("投标文件应当对招标文件的实质性要求作出响应，否则投标将被否决。")
            doc.add_paragraph("电子投标文件逾期上传或者未成功上传指定信息平台，招标人不予受理。")
            doc.add_paragraph("投标人不得存在下列情形之一。")
            doc.add_paragraph("投标人需要说明的其他内容。")
            doc.save(source_path)
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
            field_groups = structured["fieldGroups"]
            field_group_keys = list(field_groups.keys())
            self.assertIn("projectBasics", field_group_keys)
            self.assertIn("businessResponse", field_group_keys)
            self.assertIn("qualificationSupport", field_group_keys)
            self.assertIn("commitmentRequirements", field_group_keys)
            self.assertIn("qualificationRequirements", field_group_keys)
            self.assertIn("bidderInstructions", field_group_keys)
            self.assertIn("commercialRejectionClauses", field_group_keys)
            self.assertEqual(set(structured["scoringCriteria"].keys()), {"business", "price", "compliance"})
            self.assertEqual(len(structured["scoringCriteria"]["compliance"]), 1)
            self.assertEqual(structured["scoringCriteria"]["compliance"][0]["scoringItem"], "投标保证金")
            self.assertEqual(len(structured["scoringCriteria"]["business"]), 1)
            self.assertEqual(structured["scoringCriteria"]["business"][0]["scoringItem"], "企业业绩")
            self.assertEqual(len(structured["scoringCriteria"]["price"]), 1)
            self.assertEqual(structured["scoringCriteria"]["price"][0]["scoringItem"], "评标价")
            project_basics = field_groups["projectBasics"]
            self.assertEqual(field_by_key(project_basics, "projectName")["value"], "华能甘肃100MW风电项目")
            self.assertEqual(field_by_key(project_basics, "tenderNo")["value"], "HN-BUS-2026-001")
            self.assertEqual(field_by_key(project_basics, "tenderer")["value"], "华能集团")
            self.assertEqual(field_by_key(project_basics, "tenderAgency")["value"], "睿采数动公司")
            self.assertEqual(field_by_key(project_basics, "bidDeadline")["value"], "2026-01-26")
            self.assertGreaterEqual(len(field_groups["qualificationRequirements"]), 1)
            self.assertEqual(field_groups["bidderInstructions"][0]["clauseNo"], "1.1.2")
            self.assertEqual(field_groups["bidderInstructions"][1]["clauseName"], "招标代理机构")
            self.assertGreaterEqual(len(field_groups["commercialRejectionClauses"]), 2)
            self.assertTrue(any("否决" in row["content"] for row in field_groups["commercialRejectionClauses"]))
            self.assertTrue(any("不予受理" in row["content"] for row in field_groups["commercialRejectionClauses"]))
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
