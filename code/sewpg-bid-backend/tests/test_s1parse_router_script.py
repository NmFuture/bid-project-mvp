from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class S1ParseRouterScriptTests(unittest.TestCase):
    def router_path(self) -> Path:
        backend_root = Path(__file__).resolve().parents[1]
        return backend_root / "opencode" / "skill" / "s1parse_router.py"

    def test_router_executes_technical_manifest(self) -> None:
        router_path = self.router_path()

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
        router_path = self.router_path()

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

    def test_business_router_outputs_readable_qualification_requirements(self) -> None:
        router_path = self.router_path()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "商务资格要求.md"
            source_path.write_text(
                "\n".join(
                    [
                        "# 商务招标文件",
                        "第一章 招标公告",
                        "3. 投标人资格要求",
                        "3.1 通用资格条件",
                        "3.1.1 投标人为中华人民共和国境内合法注册的独立法人或其他组织。",
                        "3.2 专用资格条件",
                        "3.2.1 业绩要求：",
                        "标段一（需同时满足）：",
                        "（1）投标人须提供近3年同类项目合同业绩。",
                        "3.2.2 本项目不接受联合体投标。",
                        "第三章 评标办法",
                        "满足最低资格要求的合同业绩数量者得基础分12分。",
                        "3.5 资格审查资料\t23",
                    ]
                ),
                encoding="utf-8",
            )
            output_path = tmp_path / "s1_structured_result.json"
            manifest_path = tmp_path / "s1_parse_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "PRJ-BUSINESS-QUAL-ROUTER",
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

            self.assertEqual(json.loads(completed.stdout)["schemaVersion"], "bid-business-tender-structured-v1")
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            rows = payload["structured"]["fieldGroups"]["qualificationRequirements"]
            contents = "\n".join(row["content"] for row in rows)
            self.assertIn("中华人民共和国境内合法注册", contents)
            self.assertIn("近3年同类项目合同业绩", contents)
            self.assertIn("不接受联合体投标", contents)
            self.assertNotIn("基础分12分", contents)
            self.assertNotIn("资格审查资料\t23", contents)
            self.assertTrue(any(row["applicableScope"] == "标段一" for row in rows))
            self.assertTrue(all("sourceText" in row and "L" not in row["sourceText"] for row in rows))

    def test_business_s1parse_router_still_targets_structured_parser_when_template_extraction_path_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_dir = Path(temp)
            combined_path = temp_dir / "combined.txt"
            structured_path = temp_dir / "structured.json"
            extraction_path = temp_dir / "business_template_extraction.json"
            manifest_path = temp_dir / "s1_parse_manifest.json"
            combined_path.write_text("第六章 投标文件格式\n商务评分 企业业绩 5分", encoding="utf-8")
            structured_path.write_text(json.dumps({"structured": {"appendices": []}}, ensure_ascii=False), encoding="utf-8")
            extraction_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-business-template-extractor-v1",
                        "appendices": [],
                        "summary": {"templateCount": 0},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "proj-1",
                        "parseProfile": "business",
                        "combinedTextPath": str(combined_path),
                        "structuredResultPath": str(structured_path),
                        "businessTemplateExtractionPath": str(extraction_path),
                        "documents": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(self.router_path()), str(manifest_path)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(structured_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["structured"]["targetSkill"], "bid-business-tender-structured-parser")
            self.assertEqual(payload["structured"]["schemaVersion"], "bid-business-tender-structured-v1")
