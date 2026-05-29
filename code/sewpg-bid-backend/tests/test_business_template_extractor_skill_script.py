import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from docx import Document

from app.services.business_template_extractor import (
    build_business_template_extractor_manifest,
    convert_extractor_appendices,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "opencode" / "skill" / "bid-business-template-extractor" / "scripts" / "run_from_manifest.py"


def build_business_format_docx(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("这里不是模板。")
    doc.add_page_break()
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_paragraph("投标函的格式(1A)")
    doc.add_paragraph("致：招标人")
    doc.add_paragraph("投标人(盖公章)：")
    doc.add_paragraph("法定代表人或其委托代理人(签字)：")
    doc.add_paragraph("地址：")
    doc.add_paragraph("电话：")
    doc.add_paragraph("传真：")
    doc.add_paragraph("日期：       年    月   日")
    doc.add_page_break()
    doc.add_paragraph("法定代表人（单位负责人）身份证明：B")
    doc.add_paragraph("姓名：")
    doc.save(path)


def docx_text(path: Path) -> str:
    doc = Document(str(path))
    return "\n".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip())


class BusinessTemplateExtractorSkillScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="business-template-extractor-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_runner_writes_appendices_and_preserves_bid_letter_tail(self) -> None:
        source = self.temp_dir / "招标文件.docx"
        output_dir = self.temp_dir / "output"
        manifest = self.temp_dir / "manifest.json"
        build_business_format_docx(source)
        manifest.write_text(
            json.dumps(
                {
                    "projectId": "proj-test",
                    "outputDir": str(output_dir),
                    "documents": [
                        {
                            "id": "DOC-1",
                            "name": "招标文件.docx",
                            "sourcePath": str(source),
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [sys.executable, str(RUNNER), str(manifest)],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["schemaVersion"], "bid-business-template-extractor-v1")
        self.assertEqual(payload["skillName"], "bid-business-template-extractor")
        self.assertEqual(payload["summary"]["templateCount"], len(payload["appendices"]))
        bid_letter = next(item for item in payload["appendices"] if "投标函" in item["title"])
        self.assertEqual(bid_letter["artifactType"], "business_attachment_template")
        self.assertEqual(bid_letter["sourceDocumentId"], "DOC-1")
        self.assertTrue(Path(bid_letter["docxPath"]).is_file())
        text = docx_text(Path(bid_letter["docxPath"]))
        self.assertIn("投标人(盖公章)：", text)
        self.assertIn("法定代表人或其委托代理人(签字)：", text)
        self.assertIn("日期：       年    月   日", text)
        self.assertNotIn("法定代表人（单位负责人）身份证明：B", text)


class BusinessTemplateExtractorWrapperTests(unittest.TestCase):
    def test_build_manifest_keeps_only_docx_sources_and_output_dir(self) -> None:
        output_dir = Path("C:/tmp/business-template-output")
        manifest = build_business_template_extractor_manifest(
            project_id="proj-1",
            documents=[
                {"id": "DOC-1", "name": "招标.docx", "sourcePath": "C:/tmp/招标.docx"},
                {"id": "DOC-2", "name": "说明.txt", "sourcePath": "C:/tmp/说明.txt"},
            ],
            output_dir=output_dir,
        )

        self.assertEqual(manifest["projectId"], "proj-1")
        self.assertEqual(manifest["outputDir"], str(output_dir))
        self.assertEqual(len(manifest["documents"]), 1)
        self.assertEqual(manifest["documents"][0]["id"], "DOC-1")

    def test_convert_extractor_appendices_preserves_docx_path_for_prepare_outputs(self) -> None:
        payload = {
            "appendices": [
                {
                    "id": "APPX-0007",
                    "title": "附件2 投标价格表\nA投标价格总表\n表1 A-1  标段一",
                    "artifactType": "business_attachment_template",
                    "templateType": "business_template",
                    "templateSectionTitle": "第六章 投标文件格式",
                    "status": "generated",
                    "docxPath": "C:/tmp/TPL-0001.docx",
                    "sourceDocumentId": "DOC-1",
                    "sourceDocumentName": "招标.docx",
                }
            ]
        }

        appendices = convert_extractor_appendices(payload)

        self.assertEqual(len(appendices), 1)
        self.assertEqual(appendices[0]["id"], "APPX-0007")
        self.assertEqual(appendices[0]["title"], "附件2 投标价格表\nA投标价格总表\n表1 A-1  标段一")
        self.assertEqual(appendices[0]["artifactType"], "business_attachment_template")
        self.assertEqual(appendices[0]["extractionMode"], "business_template_extractor_skill")
        self.assertEqual(appendices[0]["docxPath"], "C:/tmp/TPL-0001.docx")
        self.assertEqual(appendices[0]["workspacePath"], "")


if __name__ == "__main__":
    unittest.main()
