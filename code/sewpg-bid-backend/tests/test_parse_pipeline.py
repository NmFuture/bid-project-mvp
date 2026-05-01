from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services.store import store


def build_docx_bytes(*lines: str) -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(file_obj)
    return file_obj.getvalue()


def build_appendix_docx_bytes() -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    doc.add_paragraph("附表1：供货范围空表")
    table = doc.add_table(rows=3, cols=3)
    values = [
        ["序号", "设备名称", "投标响应"],
        ["1", "风力发电机组", ""],
        ["2", "塔筒", ""],
    ]
    for row_index, row in enumerate(values):
        for col_index, value in enumerate(row):
            table.cell(row_index, col_index).text = value
    doc.save(file_obj)
    return file_obj.getvalue()


def field_by_key(items: list[dict], key: str) -> dict:
    return next(item for item in items if item["key"] == key)


class ParsePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.ensure_dirs()

        store.reset_for_tests()
        store._ensure_db()
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def create_project(self) -> str:
        response = self.client.post(
            "/api/projects",
            json={"name": "解析测试项目", "customerName": "测试业主"},
        )
        response.raise_for_status()
        return response.json()["id"]

    def test_upload_and_parse_docx_extracts_text_and_preview(self) -> None:
        project_id = self.create_project()
        file_bytes = build_docx_bytes(
            "上海电气风电项目招标文件",
            "第一章 项目概况",
            "本项目建设地点位于江苏。",
        )

        response = self.client.post(
            f"/api/projects/{project_id}/parse-results/upload-and-run",
            files=[
                (
                    "tenderFiles",
                    ("招标文件.docx", file_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["summary"]["fileCount"], 1)
        self.assertGreater(payload["summary"]["textLength"], 10)
        self.assertIn("上海电气风电项目招标文件", payload["summary"]["textPreview"])

    def test_upload_and_parse_markdown_extracts_text_and_preview(self) -> None:
        project_id = self.create_project()
        file_bytes = "# Markdown 招标说明\n\n本项目允许使用 Markdown 素材文件。".encode("utf-8")

        response = self.client.post(
            f"/api/projects/{project_id}/parse-results/upload-and-run",
            files=[
                (
                    "tenderFiles",
                    ("招标说明.md", file_bytes, "text/markdown"),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["sourceFiles"][0]["type"], "MD")
        self.assertIn("Markdown 招标说明", payload["summary"]["textPreview"])

    def test_upload_and_parse_multiple_tenders_extracts_structured_requirements_and_dates(self) -> None:
        project_id = self.create_project()
        main_tender = "\n".join(
            [
                "# 总发包招标文件",
                "项目名称：华能甘肃100MW风电项目",
                "招标编号：HN-2026-001",
                "招标人：华能集团",
                "项目起始日期：2026年6月1日",
                "投标截止日期：2026年9月30日",
                "评分细则：技术方案30分，供货保障10分。",
                "交货周期：2026年10月1日至2027年3月31日",
            ]
        ).encode("utf-8")
        child_tender = "\n".join(
            [
                "# 子项目招标文件",
                "单机容量：6.25MW",
                "叶轮直径：200m",
                "轮毂高度：120m",
                "可利用率：97%",
                "功率曲线保证率：95%",
                "环境适应性要求：低温-30℃、覆冰、防雷暴。",
                "专题方案要求：叶片专题方案、变桨系统专题方案。",
            ]
        ).encode("utf-8")

        response = self.client.post(
            f"/api/projects/{project_id}/parse-results/upload-and-run",
            files=[
                ("tenderFiles", ("总发包招标文件.md", main_tender, "text/markdown")),
                ("tenderFiles", ("子项目招标文件.md", child_tender, "text/markdown")),
            ],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["fileCount"], 2)
        self.assertGreaterEqual(payload["summary"]["extractedCount"], 10)

        category_labels = {category["label"] for category in payload["structured"]["categories"]}
        self.assertIn("评分细则", category_labels)
        self.assertIn("项目基础信息", category_labels)
        self.assertIn("风机核心参数", category_labels)
        self.assertIn("性能保证指标", category_labels)
        self.assertIn("环境适应性要求", category_labels)
        self.assertIn("专题方案要求", category_labels)

        item_types = {item["type"] for item in payload["items"]}
        self.assertIn("评分细则", item_types)
        self.assertIn("项目基础信息", item_types)
        self.assertIn("风机核心参数", item_types)
        self.assertIn("性能保证指标", item_types)
        self.assertIn("环境适应性要求", item_types)
        self.assertIn("专题方案要求", item_types)

        source_files = {item["sourceFile"] for item in payload["items"]}
        self.assertIn("总发包招标文件.md", source_files)
        self.assertIn("子项目招标文件.md", source_files)
        self.assertTrue(all(item.get("evidence") for item in payload["items"]))
        self.assertTrue(all(item.get("evidenceLocation") for item in payload["items"]))

        parsed_dates = payload["structured"]["projectDates"]
        self.assertEqual(parsed_dates["startDate"], "2026-06-01")
        self.assertEqual(parsed_dates["endDate"], "2026-09-30")

        project = store._require(project_id)
        self.assertEqual(project["startDate"], "2026-06-01")
        self.assertEqual(project["endDate"], "2026-09-30")
        self.assertEqual(project["deadline"], "2026-09-30")

    def test_parse_result_exposes_fixed_fields_presence_and_appendix_docx_assets(self) -> None:
        project_id = self.create_project()
        tender = "\n".join(
            [
                "# 招标文件",
                "项目名称：华能甘肃100MW风电项目",
                "招标编号：HN-2026-001",
                "招标人：华能集团",
                "管理单位：华能甘肃公司",
                "标段规模：100MW",
                "交货周期：2026年10月1日至2027年3月31日",
                "质保期：5年",
                "技术承诺：投标人应承诺满足全部技术规范。",
                "评分细则：技术方案30分，需提供技术响应表和证明材料；供货保障10分，需提供供货计划。",
                "单机容量：6.25MW",
                "叶轮直径：200m",
                "轮毂高度：120m",
                "叶片最低点距地：20m",
                "塔筒型式：钢混塔筒",
                "箱变型式：华式箱变",
                "安全等级：IEC IIB",
                "空气密度：1.225kg/m3",
                "风速：8.5m/s",
                "湍流强度：0.14",
                "功率曲线：投标人应提供经认证功率曲线。",
                "可利用率：97%",
                "发电量：年上网电量不少于300GWh",
                "涉网性能：满足高低电压穿越要求。",
                "环境适应性：抗低温、抗覆冰防凝露、防潮湿、防雷暴、防风沙、抗高温。",
                "专题方案：应提供叶片专题、变桨系统专题、主轴专题、齿轮箱专题。",
                "供货范围：风力发电机组、塔筒、箱变及备品备件。",
                "考核条款：发电量考核、可利用率考核、功率曲线考核、部件考核、认证考核。",
                "附表1：技术参数响应表",
                "| 序号 | 参数 | 投标响应 |",
                "| --- | --- | --- |",
                "| 1 | 单机容量 | |",
                "| 2 | 叶轮直径 | |",
            ]
        ).encode("utf-8")

        response = self.client.post(
            f"/api/projects/{project_id}/parse-results/upload-and-run",
            files=[("tenderFiles", ("招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        structured = payload["structured"]
        field_groups = structured["fieldGroups"]

        project_basics = field_groups["projectBasics"]
        self.assertEqual(field_by_key(project_basics, "projectName")["value"], "华能甘肃100MW风电项目")
        self.assertEqual(field_by_key(project_basics, "tenderNo")["value"], "HN-2026-001")
        self.assertEqual(field_by_key(project_basics, "tenderer")["value"], "华能集团")
        self.assertEqual(field_by_key(project_basics, "managementUnit")["value"], "华能甘肃公司")
        self.assertEqual(field_by_key(project_basics, "bidSectionScale")["value"], "100MW")
        self.assertEqual(field_by_key(project_basics, "deliveryPeriod")["value"], "2026年10月1日至2027年3月31日")
        self.assertEqual(field_by_key(project_basics, "warrantyPeriod")["value"], "5年")
        self.assertIn("全部技术规范", field_by_key(project_basics, "technicalCommitment")["value"])

        turbine = field_groups["turbineCoreParameters"]
        self.assertEqual(field_by_key(turbine, "singleCapacity")["value"], "6.25MW")
        self.assertEqual(field_by_key(turbine, "rotorDiameter")["value"], "200m")
        self.assertEqual(field_by_key(turbine, "hubHeight")["value"], "120m")
        self.assertEqual(field_by_key(turbine, "bladeTipClearance")["value"], "20m")
        self.assertEqual(field_by_key(turbine, "towerType")["value"], "钢混塔筒")
        self.assertEqual(field_by_key(turbine, "boxTransformerType")["value"], "华式箱变")
        self.assertEqual(field_by_key(turbine, "safetyClass")["value"], "IEC IIB")
        self.assertEqual(field_by_key(turbine, "airDensity")["value"], "1.225kg/m3")
        self.assertEqual(field_by_key(turbine, "windSpeed")["value"], "8.5m/s")
        self.assertEqual(field_by_key(turbine, "turbulenceIntensity")["value"], "0.14")

        performance = field_groups["performanceGuarantees"]
        self.assertIn("认证功率曲线", field_by_key(performance, "powerCurve")["value"])
        self.assertEqual(field_by_key(performance, "availability")["value"], "97%")
        self.assertEqual(field_by_key(performance, "generation")["value"], "年上网电量不少于300GWh")
        self.assertIn("电压穿越", field_by_key(performance, "gridPerformance")["value"])

        scoring = field_groups["scoringCriteria"]
        self.assertEqual(scoring[0]["scoringItem"], "技术方案")
        self.assertEqual(scoring[0]["score"], "30分")
        self.assertIn("证明材料", scoring[0]["proofRequirement"])
        self.assertEqual(scoring[1]["scoringItem"], "供货保障")
        self.assertEqual(scoring[1]["score"], "10分")
        self.assertIn("供货计划", scoring[1]["proofRequirement"])

        presence = structured["requirementPresence"]
        self.assertEqual(presence["topicPlans"]["status"], "present")
        self.assertIn("叶片专题", presence["topicPlans"]["summary"])
        self.assertEqual(presence["supplyScope"]["status"], "present")
        self.assertIn("风力发电机组", presence["supplyScope"]["summary"])
        self.assertEqual(presence["assessmentTerms"]["status"], "present")
        self.assertIn("发电量考核", presence["assessmentTerms"]["summary"])

        appendices = structured["appendices"]
        self.assertEqual(len(appendices), 1)
        self.assertEqual(appendices[0]["title"], "附表1：技术参数响应表")
        self.assertEqual(appendices[0]["status"], "generated")
        self.assertEqual(appendices[0]["rowCount"], 3)
        appendix_path = Path(appendices[0]["docxPath"])
        self.assertTrue(appendix_path.exists())
        self.assertIn(str(settings.documents_dir / project_id / "technical-workspace" / "appendices"), str(appendix_path))
        appendix_doc = Document(str(appendix_path))
        self.assertEqual(len(appendix_doc.tables), 1)
        self.assertEqual(appendix_doc.tables[0].cell(0, 1).text, "参数")
        self.assertEqual(appendix_doc.tables[0].cell(1, 2).text, "")

    def test_parse_docx_appendix_table_generates_workspace_docx(self) -> None:
        project_id = self.create_project()
        response = self.client.post(
            f"/api/projects/{project_id}/parse-results/upload-and-run",
            files=[
                (
                    "tenderFiles",
                    (
                        "含附表招标文件.docx",
                        build_appendix_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        self.assertEqual(len(appendices), 1)
        self.assertEqual(appendices[0]["status"], "generated")
        self.assertEqual(appendices[0]["rowCount"], 3)
        appendix_doc = Document(appendices[0]["docxPath"])
        self.assertEqual(appendix_doc.tables[0].cell(0, 1).text, "设备名称")
        self.assertEqual(appendix_doc.tables[0].cell(1, 2).text, "")

    def test_parse_progress_records_real_steps_and_completion(self) -> None:
        project_id = self.create_project()
        tender = "项目名称：进度测试项目\n单机容量：6.25MW\n".encode("utf-8")

        before = self.client.get(f"/api/projects/{project_id}/parse-results/progress")
        self.assertEqual(before.status_code, 200)
        self.assertEqual(before.json()["status"], "idle")

        response = self.client.post(
            f"/api/projects/{project_id}/parse-results/upload-and-run",
            files=[("tenderFiles", ("招标文件.md", tender, "text/markdown"))],
        )
        self.assertEqual(response.status_code, 200)

        progress = self.client.get(f"/api/projects/{project_id}/parse-results/progress")
        self.assertEqual(progress.status_code, 200)
        payload = progress.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["percentage"], 100)
        steps = [event["step"] for event in payload["events"]]
        self.assertIn("upload", steps)
        self.assertIn("extract", steps)
        self.assertIn("skill", steps)
        self.assertIn("appendix", steps)
        self.assertIn("complete", steps)

    def test_project_create_and_update_support_start_and_end_dates(self) -> None:
        response = self.client.post(
            "/api/projects",
            json={
                "name": "日期测试项目",
                "customerName": "测试业主",
                "startDate": "2026-05-10",
                "endDate": "2026-08-20",
                "deadline": "2026-08-20",
            },
        )
        self.assertEqual(response.status_code, 200)
        created = response.json()
        self.assertEqual(created["startDate"], "2026-05-10")
        self.assertEqual(created["endDate"], "2026-08-20")
        self.assertEqual(created["deadline"], "2026-08-20")

        update_response = self.client.put(
            f"/api/projects/{created['id']}",
            json={
                "startDate": "2026-05-15",
                "endDate": "2026-09-01",
                "deadline": "2026-09-01",
            },
        )
        self.assertEqual(update_response.status_code, 200)
        updated = update_response.json()
        self.assertEqual(updated["startDate"], "2026-05-15")
        self.assertEqual(updated["endDate"], "2026-09-01")
        self.assertEqual(updated["deadline"], "2026-09-01")

        list_response = self.client.get("/api/projects")
        self.assertEqual(list_response.status_code, 200)
        listed = list_response.json()["items"][0]
        self.assertEqual(listed["startDate"], "2026-05-15")
        self.assertEqual(listed["endDate"], "2026-09-01")

    def test_upload_and_parse_persists_text_to_disk_artifact(self) -> None:
        project_id = self.create_project()
        file_bytes = build_docx_bytes(
            "招标文件正文",
            "第二章 技术方案",
            "这里是一段比较长的测试内容，用于验证解析结果不会直接塞进项目状态数据库，而是落到磁盘文件。",
        )

        response = self.client.post(
            f"/api/projects/{project_id}/parse-results/upload-and-run",
            files=[
                (
                    "tenderFiles",
                    ("招标文件.docx", file_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        project = store._require(project_id)
        parse_storage = project["parse_storage"]
        combined_text_path = Path(parse_storage["combinedTextPath"])
        self.assertTrue(combined_text_path.exists())
        content = combined_text_path.read_text(encoding="utf-8")
        self.assertIn("第二章 技术方案", content)
        self.assertGreater(parse_storage["documents"][0]["textLength"], 10)

    def test_template_only_reparse_works_after_tender_uploaded(self) -> None:
        project_id = self.create_project()
        tender_bytes = build_docx_bytes("招标文件正文", "项目概况", "这是第一次上传的招标文件。")
        template_bytes = build_docx_bytes("投标模板", "封面", "这是后补上传的模板文件。")

        first_response = self.client.post(
            f"/api/projects/{project_id}/parse-results/upload-and-run",
            files=[
                (
                    "tenderFiles",
                    ("招标文件.docx", tender_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                )
            ],
        )
        self.assertEqual(first_response.status_code, 200)

        second_response = self.client.post(
            f"/api/projects/{project_id}/parse-results/upload-and-run",
            files=[
                (
                    "templateFiles",
                    ("投标模板.docx", template_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                )
            ],
        )

        self.assertEqual(second_response.status_code, 200)
        payload = second_response.json()
        self.assertEqual(payload["summary"]["fileCount"], 1)
        self.assertEqual(len(payload["project"]["templateFiles"]), 1)
        self.assertEqual(payload["project"]["templateFiles"][0]["name"], "投标模板.docx")

    def test_parse_inputs_use_fallback_template_when_project_has_no_template(self) -> None:
        project_id = self.create_project()
        tender_bytes = build_docx_bytes("招标文件正文", "项目概况", "项目没有单独上传投标模板。")
        response = self.client.post(
            f"/api/projects/{project_id}/parse-results/upload-and-run",
            files=[
                (
                    "tenderFiles",
                    ("招标文件.docx", tender_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                )
            ],
        )
        self.assertEqual(response.status_code, 200)

        fallback_path = settings.uploads_dir / project_id / "fallback-template" / "投标文件-模板.docx"
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        fallback_path.write_bytes(build_docx_bytes("Fallback 投标模板", "第一章 模板章节"))
        fallback_record = {
            "id": "FBT-DEFAULT",
            "name": "投标文件-模板.docx",
            "stored_name": "投标文件-模板.docx",
            "size_bytes": fallback_path.stat().st_size,
            "size_label": store.format_size(fallback_path.stat().st_size),
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "path": str(fallback_path),
            "source": "fallback",
            "isFallback": True,
            "minioBucket": "bid-templates",
            "minioKey": "templates/fallback/technical/投标文件-模板.docx",
        }

        with patch("app.services.template_store.resolve_fallback_bid_template_file", return_value=fallback_record):
            _, template_files = store.get_parse_inputs(project_id)

        self.assertEqual(len(template_files), 1)
        self.assertEqual(template_files[0]["name"], "投标文件-模板.docx")
        self.assertTrue(template_files[0]["isFallback"])
        self.assertEqual(template_files[0]["minioKey"], "templates/fallback/technical/投标文件-模板.docx")

    def test_project_template_overrides_fallback_template(self) -> None:
        project_id = self.create_project()
        tender_bytes = build_docx_bytes("招标文件正文", "项目概况", "项目后续上传自己的投标模板。")
        template_bytes = build_docx_bytes("项目投标模板", "第一章 项目模板章节")
        response = self.client.post(
            f"/api/projects/{project_id}/parse-results/upload-and-run",
            files=[
                (
                    "tenderFiles",
                    ("招标文件.docx", tender_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                ),
                (
                    "templateFiles",
                    ("项目模板.docx", template_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                ),
            ],
        )
        self.assertEqual(response.status_code, 200)

        fallback_record = {
            "id": "FBT-DEFAULT",
            "name": "投标文件-模板.docx",
            "path": "/tmp/fallback.docx",
            "source": "fallback",
            "isFallback": True,
        }
        with patch("app.services.template_store.resolve_fallback_bid_template_file", return_value=fallback_record):
            _, template_files = store.get_parse_inputs(project_id)

        self.assertEqual(len(template_files), 1)
        self.assertEqual(template_files[0]["name"], "项目模板.docx")
        self.assertNotEqual(template_files[0].get("source"), "fallback")


if __name__ == "__main__":
    unittest.main()
