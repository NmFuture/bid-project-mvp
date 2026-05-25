from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from docx import Document
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import parsing as parsing_service
from app.services.file_utils import format_size_mb
from app.services.bid_parse_state import complete_parse_state
from app.services.bid_project_state import project_parse_input_records
from app.services.store import store


def build_docx_bytes(*lines: str) -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(file_obj)
    return file_obj.getvalue()


def parse_inputs_for_tests(project_id: str):
    project = store.get_project_runtime_state(project_id)
    return project_parse_input_records(project_id, project)


def complete_parse_for_tests(
    project_id: str,
    tender_files: list[dict],
    template_files: list[dict],
    *,
    summary: dict | None = None,
    parse_storage: dict | None = None,
) -> dict:
    project = store.require_project_for_update(project_id)
    payload = complete_parse_state(
        project,
        tender_files,
        template_files,
        summary=summary,
        parse_storage=parse_storage,
    )
    store.persist_project_state(project)
    return payload


def build_docx_blocks_bytes(*blocks: str | list[list[str]]) -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    for block in blocks:
        if isinstance(block, str):
            doc.add_paragraph(block)
            continue
        if not block:
            continue
        column_count = max(len(row) for row in block)
        table = doc.add_table(rows=len(block), cols=column_count)
        for row_index, row in enumerate(block):
            for col_index in range(column_count):
                table.cell(row_index, col_index).text = row[col_index] if col_index < len(row) else ""
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


def build_appendix_with_merges_docx_bytes() -> bytes:
    """Build an RFP-like docx whose appendix table uses both horizontal and vertical
    cell merges, so we can assert that the parser preserves these structures end-to-end."""

    file_obj = io.BytesIO()
    doc = Document()
    doc.add_paragraph("附表D.1 标准及风电场空气密度功率曲线")
    table = doc.add_table(rows=4, cols=4)
    table.style = "Table Grid"
    # Row 0 header: merge all 4 cells into one banner
    table.cell(0, 0).text = "机型：投标机型1"
    table.cell(0, 0).merge(table.cell(0, 3))
    # Row 1 sub-header: merge last two columns into "对比图"
    headers = ["风速区间(m/s)", "区间平均风速(m/s)", "标准空气密度下功率(kW)", "对比图"]
    for col_index, value in enumerate(headers):
        table.cell(1, col_index).text = value
    table.cell(1, 3).merge(table.cell(1, 3))
    # Row 2: data row, with cols 2-3 vertically merged into row 3 (vMerge)
    table.cell(2, 0).text = "0.00-0.50"
    table.cell(2, 1).text = "0"
    table.cell(2, 2).text = "/"
    table.cell(2, 3).text = "/"
    # Row 3: another data row; col 3 merged into row 2's col 3 (vertical)
    table.cell(3, 0).text = "0.50-1.00"
    table.cell(3, 1).text = "0.5"
    table.cell(3, 2).text = "/"
    table.cell(3, 3).text = "/"
    table.cell(2, 3).merge(table.cell(3, 3))
    doc.save(file_obj)
    return file_obj.getvalue()


def build_business_attachment_templates_docx_bytes() -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("此处为普通正文，不应被提取为商务附件模板。")
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_paragraph("附件1 投标函")
    doc.add_paragraph("致：华能集团")
    doc.add_paragraph("我方已仔细研究招标文件的全部内容，愿意参加本项目投标。")
    doc.add_paragraph("投标人（盖章）：____________")
    doc.add_paragraph("附件2 开标价格表")
    table = doc.add_table(rows=3, cols=3)
    table.style = "Table Grid"
    table.cell(0, 0).text = "开标价格表"
    table.cell(0, 0).merge(table.cell(0, 2))
    values = [
        ["序号", "项目名称", "投标报价"],
        ["1", "", ""],
    ]
    for row_index, row in enumerate(values, start=1):
        for col_index, value in enumerate(row):
            table.cell(row_index, col_index).text = value
    doc.add_paragraph("附件3 法定代表人授权书")
    doc.add_paragraph("本人授权以下代表作为我方合法代理人参加本项目投标。")
    doc.add_paragraph("授权代表签字：____________")
    doc.save(file_obj)
    return file_obj.getvalue()


def build_business_attachment_templates_with_toc_docx_bytes() -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    doc.add_paragraph("目录")
    doc.add_paragraph("第六章 投标文件格式 108")
    doc.add_paragraph("附件1 投标函 109")
    doc.add_paragraph("附件3 货物规格一览表 110")
    doc.add_paragraph("附件6 履约保证函格式承诺书和质量保函 111")
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("普通招标公告正文。")
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_paragraph("附件1 投标函")
    doc.add_paragraph("致：华能集团")
    doc.add_paragraph("投标人（盖章）：____________")
    doc.add_paragraph("附件3 货物规格一览表")
    table = doc.add_table(rows=3, cols=4)
    table.style = "Table Grid"
    values = [
        ["序号", "货物名称", "规格型号", "数量"],
        ["1", "风力发电机组", "", ""],
        ["2", "塔筒", "", ""],
    ]
    for row_index, row in enumerate(values):
        for col_index, value in enumerate(row):
            table.cell(row_index, col_index).text = value
    doc.add_paragraph("附件6 履约保证函格式承诺书和质量保函")
    doc.add_paragraph("我方承诺按招标文件要求提交履约保证函并承担质量保函责任。")
    doc.add_paragraph("投标人（盖章）：____________")
    doc.save(file_obj)
    return file_obj.getvalue()


def build_business_fingerprint_only_tables_docx_bytes() -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("本章为公告。")
    doc.add_heading("商务标格式", level=1)
    doc.add_paragraph("投标报价明细")
    table = doc.add_table(rows=3, cols=4)
    table.style = "Table Grid"
    values = [
        ["序号", "货物名称", "规格型号", "数量"],
        ["1", "风力发电机组", "", ""],
        ["2", "塔筒", "", ""],
    ]
    for row_index, row in enumerate(values):
        for col_index, value in enumerate(row):
            table.cell(row_index, col_index).text = value
    doc.add_heading("合同条款", level=1)
    doc.add_paragraph("本章不属于投标文件格式。")
    doc.save(file_obj)
    return file_obj.getvalue()


def build_business_commitment_template_alignment_docx_bytes() -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    doc.add_paragraph("第二章 投标人须知")
    doc.add_paragraph("投标人须无条件承诺在本采购项目第一台合同设备供货前取得本条a和b所述材料，需提供承诺书。")
    doc.add_heading("第六章 投标文件格式", level=1)
    doc.add_paragraph("附件1 材料取得承诺书")
    doc.add_paragraph("我方承诺在本采购项目第一台合同设备供货前取得本条a和b所述材料。")
    doc.add_paragraph("投标人（盖章）：____________")
    doc.save(file_obj)
    return file_obj.getvalue()


def field_by_key(items: list[dict], key: str) -> dict:
    return next(item for item in items if item["key"] == key)


def sample_evaluation_docx_bytes() -> bytes:
    return build_docx_blocks_bytes(
        "第三章 评标办法（综合评估法）",
        "附表2：技术评分标准表",
        [
            ["序号", "评分项", "分值", "得分点", "证明材料要求"],
            ["1", "技术方案", "30分", "总体方案完整、技术路线先进得满分。", "提供技术方案和技术承诺函。"],
            ["2", "供货保障", "10分", "供货计划合理、保障措施充分得满分。", "提供供货计划。"],
        ],
        "附表3：商务评分标准表",
        [
            ["序号", "评分项", "分值", "得分点", "证明材料要求"],
            ["1", "企业业绩", "20分", "近三年同类风电项目业绩满足要求得满分。", "提供合同或中标通知书。"],
            ["2", "财务状况", "10分", "财务状况良好得满分。", "提供审计报告。"],
        ],
        "附表4：投标报价评分标准",
        [
            ["序号", "评分项", "满分", "评分办法"],
            ["1", "投标报价", "100分", "以评标基准价为基础计算报价得分。"],
        ],
        "附表5：投标度电成本评分标准",
        [
            ["序号", "评分项", "满分", "评分办法"],
            ["1", "度电成本", "100分", "按度电成本由低到高计算得分。"],
        ],
        "附表1：符合性审查标准表",
        [
            ["序号", "审查项目", "审查标准", "证明材料要求"],
            ["1", "投标文件签署", "投标文件按招标文件要求签字盖章。", "提供签字盖章页。"],
        ],
    )


def sample_technical_spec_docx_bytes() -> bytes:
    return build_docx_blocks_bytes(
        "第二卷 技术规范书",
        "1.1.1 项目概况",
        [
            ["项目名称", "华能甘肃100MW风电项目"],
            ["招标编号", "HN-2026-001"],
            ["招标人", "华能集团"],
            ["管理单位", "华能甘肃公司"],
            ["标段规模", "100MW"],
            ["交货周期", "2026年10月1日至2027年3月31日"],
            ["质保期", "5年"],
            ["技术承诺", "投标人应承诺满足全部技术规范。"],
        ],
        "招标机型要求",
        [
            ["参数", "要求"],
            ["单机容量", "6.25MW"],
            ["叶轮直径", "200m"],
            ["轮毂高度", "120m"],
            ["叶片最低点距地", "20m"],
            ["塔筒型式", "钢混塔筒"],
            ["箱变型式", "华式箱变"],
            ["安全等级", "IEC IIB"],
            ["空气密度", "1.225kg/m3"],
            ["风速", "8.5m/s"],
            ["湍流强度", "0.14"],
        ],
        "性能保证指标",
        [
            ["指标", "要求"],
            ["功率曲线", "投标人应提供经认证功率曲线。"],
            ["可利用率", "97%"],
            ["发电量", "年上网电量不少于300GWh"],
            ["涉网性能", "满足高低电压穿越要求。"],
        ],
        "环境适应性要求",
        [
            ["要求", "说明"],
            ["抗低温", "满足-30℃低温运行。"],
            ["抗覆冰防凝露", "具备覆冰及防凝露措施。"],
            ["防潮湿", "适应高湿环境。"],
            ["防雷暴", "配置防雷保护。"],
            ["防风沙", "满足风沙环境防护。"],
            ["抗高温", "满足高温环境运行。"],
        ],
        "专题方案：应提供叶片专题、变桨系统专题、主轴专题、齿轮箱专题。",
        "供货范围：风力发电机组、塔筒、箱变及备品备件。",
        "考核条款：发电量考核、可利用率考核、功率曲线考核、部件考核、认证考核。",
    )


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
            "/api/technical/projects",
            json={"name": "解析测试项目", "customerName": "测试业主"},
        )
        response.raise_for_status()
        return response.json()["id"]

    def create_business_project(self) -> str:
        response = self.client.post(
            "/api/business/projects",
            json={"name": "商务解析测试项目", "customerName": "测试业主"},
        )
        response.raise_for_status()
        return response.json()["id"]

    def project_url(self, project_id: str) -> str:
        project = store._require(project_id)
        if project.get("bidType") == "商务标":
            return f"/api/business/projects/{project_id}"
        return f"/api/technical/projects/{project_id}"

    def parse_results_url(self, project_id: str, suffix: str = "") -> str:
        return f"{self.project_url(project_id)}/parse-results{suffix}"

    def test_upload_and_parse_docx_extracts_text_and_preview(self) -> None:
        project_id = self.create_project()
        file_bytes = build_docx_bytes(
            "上海电气风电项目招标文件",
            "第一章 项目概况",
            "本项目建设地点位于江苏。",
        )

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
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
            self.parse_results_url(project_id, "/upload-and-run"),
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

    def test_upload_and_parse_image_uses_visual_recognition_without_manual_ocr_flow(self) -> None:
        project_id = self.create_project()

        fake_response = {
            "choices": [
                {
                    "message": {
                        "content": "项目名称：图片型招标文件\n招标编号：IMG-2026-001\n投标截止日期：2026年8月20日"
                    }
                }
            ]
        }

        async def fake_post(*_args, **_kwargs):
            class Response:
                status_code = 200

                @staticmethod
                def json():
                    return fake_response

            return Response()

        with patch("app.services.system_settings.system_settings_service.get_model_secret_config") as config, patch(
            "httpx.AsyncClient.post",
            side_effect=fake_post,
        ):
            config.return_value = {
                "enabled": True,
                "baseUrl": "https://ocr.example.com/v1",
                "apiKey": "ocr-secret-key",
                "model": "deepseek-ai/DeepSeek-OCR",
                "timeoutMs": 60000,
                "maxTokens": 2048,
            }
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[
                    (
                        "tenderFiles",
                        ("图片型招标文件.png", b"\x89PNG\r\n\x1a\nfake", "image/png"),
                    )
                ],
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertIn("图片型招标文件", payload["summary"]["textPreview"])
        self.assertIn("图片文件已通过 OCR/视觉模型转为可解析文本。", payload["summary"]["warnings"])
        self.assertNotIn("ocrConfirmedFields", payload["structured"])
        self.assertEqual(payload["structured"]["projectDates"]["endDate"], "2026-08-20")

    def test_upload_and_parse_multiple_tenders_extracts_structured_requirements_and_dates(self) -> None:
        project_id = self.create_project()
        main_tender = "\n".join(
            [
                "# 总发包招标文件",
                "项目名称：华能甘肃100MW风电项目",
                "招标编号：HN-2026-001",
                "招标人：华能集团",
                "招标文件获取时间：2026年6月1日至2026年6月10日",
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
            self.parse_results_url(project_id, "/upload-and-run"),
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

    def test_bid_dates_ignore_supply_delivery_ranges(self) -> None:
        project_id = self.create_project()
        tender = "\n".join(
            [
                "# 招标文件",
                "项目名称：供货日期不应污染投标日期",
                "供货范围及交货进度",
                "主机设备2026年4月10日前开始供货，截止2026年8月30日前完成全部供货。",
                "安装调试服务期：2026年9月1日至2026年10月30日。",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        parsed_dates = response.json()["structured"]["projectDates"]
        self.assertEqual(parsed_dates["startDate"], "")
        self.assertEqual(parsed_dates["endDate"], "")

        project = store._require(project_id)
        self.assertEqual(project["startDate"], "")
        self.assertEqual(project["endDate"], "")
        self.assertEqual(project["deadline"], "")

    def test_bid_dates_parse_bid_submission_and_opening_dates(self) -> None:
        project_id = self.create_project()
        tender = "\n".join(
            [
                "# 招标公告",
                "招标文件获取时间：2026年5月8日至2026年5月15日。",
                "投标文件递交截止时间：2026年6月20日09时30分。",
                "开标时间：2026年6月20日09时30分。",
                "交货周期：2026年10月1日至2027年3月31日。",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        parsed_dates = response.json()["structured"]["projectDates"]
        self.assertEqual(parsed_dates["startDate"], "2026-05-08")
        self.assertEqual(parsed_dates["endDate"], "2026-06-20")

        project = store._require(project_id)
        self.assertEqual(project["startDate"], "2026-05-08")
        self.assertEqual(project["endDate"], "2026-06-20")
        self.assertEqual(project["deadline"], "2026-06-20")

    def test_upload_and_parse_multifile_docx_tables_builds_structured_contract(self) -> None:
        project_id = self.create_project()

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "评标办法.docx",
                        sample_evaluation_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                ),
                (
                    "tenderFiles",
                    (
                        "技术规范书.docx",
                        sample_technical_spec_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                ),
            ],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        structured = payload["structured"]

        source_documents = structured["sourceDocuments"]
        self.assertEqual(len(source_documents), 2)
        self.assertEqual(source_documents[0]["role"], "evaluation")
        self.assertEqual(source_documents[1]["role"], "technical_spec")

        scoring = structured["scoringCriteria"]
        self.assertEqual(len(scoring["technical"]), 2)
        self.assertEqual(len(scoring["business"]), 2)
        self.assertEqual(len(scoring["price"]), 1)
        self.assertEqual(len(scoring["lcoe"]), 1)
        self.assertEqual(len(scoring["compliance"]), 1)
        self.assertEqual(scoring["technical"][0]["scoringItem"], "技术方案")
        self.assertEqual(scoring["technical"][0]["score"], "30分")
        self.assertIn("技术承诺函", scoring["technical"][0]["proofRequirement"])
        self.assertEqual(scoring["business"][0]["scoringItem"], "企业业绩")
        self.assertIn("合同", scoring["business"][0]["proofRequirement"])

        for bucket in scoring.values():
            for row in bucket:
                self.assertTrue(row["sourceFile"])
                self.assertTrue(row["sourceDocumentId"])
                self.assertTrue(row["section"])
                self.assertTrue(row["evidence"])
                self.assertTrue(row["evidenceLocation"])

        field_groups = structured["fieldGroups"]
        self.assertEqual(field_by_key(field_groups["projectBasics"], "projectName")["value"], "华能甘肃100MW风电项目")
        self.assertEqual(field_by_key(field_groups["projectBasics"], "tenderNo")["value"], "HN-2026-001")
        self.assertEqual(field_by_key(field_groups["projectBasics"], "deliveryPeriod")["value"], "2026年10月1日至2027年3月31日")
        self.assertEqual(field_by_key(field_groups["turbineCoreParameters"], "singleCapacity")["value"], "6.25MW")
        self.assertEqual(field_by_key(field_groups["turbineCoreParameters"], "bladeTipClearance")["value"], "20m")
        self.assertIn("认证功率曲线", field_by_key(field_groups["performanceGuarantees"], "powerCurve")["value"])
        self.assertIn("防凝露", field_by_key(field_groups["environmentAdaptation"], "icingCondensation")["value"])

        for group in field_groups.values():
            if isinstance(group, list):
                for field in group:
                    if field["status"] == "found":
                        self.assertTrue(field["sourceFile"])
                        self.assertTrue(field["sourceDocumentId"])
                        self.assertTrue(field["evidence"])
                        self.assertTrue(field["evidenceLocation"])

        presence = structured["requirementPresence"]
        self.assertEqual(presence["topicPlans"]["status"], "present")
        self.assertEqual(presence["supplyScope"]["status"], "present")
        self.assertEqual(presence["assessmentTerms"]["status"], "present")

    def test_s1parse_skill_script_outputs_same_multifile_structured_contract(self) -> None:
        project_dir = Path(self.temp_dir.name) / "skill-script"
        project_dir.mkdir()
        evaluation_path = project_dir / "评标办法.docx"
        technical_path = project_dir / "技术规范书.docx"
        evaluation_path.write_bytes(sample_evaluation_docx_bytes())
        technical_path.write_bytes(sample_technical_spec_docx_bytes())
        evaluation_text = project_dir / "evaluation.txt"
        technical_text = project_dir / "technical.txt"
        evaluation_text.write_text("第三章 评标办法（综合评估法）\n附表2：技术评分标准表\n", encoding="utf-8")
        technical_text.write_text(
            "第二卷 技术规范书\n专题方案：应提供叶片专题、变桨系统专题、主轴专题、齿轮箱专题。\n",
            encoding="utf-8",
        )
        output_path = project_dir / "s1_structured_result.json"
        manifest_path = project_dir / "s1_parse_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "projectId": "PRJ-SKILL",
                    "structuredResultPath": str(output_path),
                    "documents": [
                        {
                            "id": "DOC-1",
                            "name": "评标办法.docx",
                            "sourcePath": str(evaluation_path),
                            "textPath": str(evaluation_text),
                        },
                        {
                            "id": "DOC-2",
                            "name": "技术规范书.docx",
                            "sourcePath": str(technical_path),
                            "textPath": str(technical_text),
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        script_path = (
            Path(__file__).resolve().parents[1]
            / "opencode"
            / "skill"
            / "bid-tender-structured-parser"
            / "scripts"
            / "run_from_manifest.py"
        )

        completed = subprocess.run(
            [sys.executable, str(script_path), str(manifest_path)],
            check=True,
            capture_output=True,
            text=True,
        )

        summary = json.loads(completed.stdout)
        self.assertEqual(summary["schemaVersion"], "bid-tender-structured-v1")
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["structured"]["scoringCriteria"]["technical"]), 2)
        self.assertEqual(len(payload["structured"]["scoringCriteria"]["business"]), 2)
        self.assertEqual(
            field_by_key(payload["structured"]["fieldGroups"]["projectBasics"], "projectName")["value"],
            "华能甘肃100MW风电项目",
        )

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
            self.parse_results_url(project_id, "/upload-and-run"),
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
        self.assertIn(str(settings.parsed_dir / project_id / "s1_appendices"), str(appendix_path))
        appendix_doc = Document(str(appendix_path))
        self.assertEqual(len(appendix_doc.tables), 1)
        self.assertEqual(appendix_doc.tables[0].cell(0, 1).text, "参数")
        self.assertEqual(appendix_doc.tables[0].cell(1, 2).text, "")

    def test_parse_docx_appendix_table_generates_workspace_docx(self) -> None:
        project_id = self.create_project()
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
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

    def test_parse_docx_appendix_preserves_cell_merges_via_source_slicing(self) -> None:
        """Ensure the appendix docx generated from a docx-source RFP keeps the
        original <w:vMerge>/<w:gridSpan> structures rather than being rebuilt
        from a flattened rows list. This is the format-preservation guarantee."""
        import zipfile

        project_id = self.create_project()
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "含合并附表招标文件.docx",
                        build_appendix_with_merges_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        self.assertEqual(len(appendices), 1)

        appendix_path = Path(appendices[0]["docxPath"])
        self.assertTrue(appendix_path.exists(), f"appendix docx missing: {appendix_path}")

        # 1. The generated appendix table must still carry cell-merge XML markers.
        with zipfile.ZipFile(appendix_path) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
        self.assertIn(
            "gridSpan",
            doc_xml,
            "horizontal merge (<w:gridSpan>) was lost: the table was rebuilt from rows instead of sliced from source",
        )
        self.assertIn(
            "vMerge",
            doc_xml,
            "vertical merge (<w:vMerge>) was lost: the table was rebuilt from rows instead of sliced from source",
        )

        # 2. The appendix should ship its own styles.xml (proof we copied the source
        #    docx, not regenerated from scratch). A regenerated python-docx file has
        #    a default styles.xml that is significantly smaller than what the source
        #    carries because the source was authored with full Word style definitions.
        with zipfile.ZipFile(appendix_path) as zf:
            self.assertIn("word/styles.xml", zf.namelist())

        # 3. The body should only retain the appendix heading + the table; everything
        #    else from the source RFP body must be removed.
        appendix_doc = Document(str(appendix_path))
        self.assertEqual(len(appendix_doc.tables), 1, "exactly one table expected in the sliced appendix")
        non_empty_paragraphs = [
            paragraph.text.strip()
            for paragraph in appendix_doc.paragraphs
            if paragraph.text.strip()
        ]
        self.assertEqual(
            non_empty_paragraphs,
            ["附表D.1 标准及风电场空气密度功率曲线"],
            "only the appendix heading paragraph should remain in body; got %r" % (non_empty_paragraphs,),
        )

    def test_parse_docx_appendix_slicing_handles_large_body_within_budget(self) -> None:
        """Regression guard: a real RFP body can have thousands of paragraphs and
        dozens of appendices. The slice path must stay O(N) overall, not O(N^2)
        per appendix. Earlier the implementation called ``body.remove(child)``
        per non-keeper, which froze the request thread for huge documents."""

        import time

        project_id = self.create_project()

        # Build an RFP-shaped docx that's representative of a real bid file:
        # ~5000 narrative paragraphs + 80 back-to-back appendices. Without
        # source-tree caching, each appendix would re-parse a multi-MB docx
        # via python-docx (several seconds per appendix => minutes total),
        # which is what froze the upload thread in production.
        narrative_blocks: list[str | list[list[str]]] = [
            f"第{i // 50 + 1}章 章节{i + 1} 这一段是正文铺垫文本，内容足够长以便撑出体积。"
            for i in range(5000)
        ]
        appendix_blocks: list[str | list[list[str]]] = []
        for i in range(1, 81):
            appendix_blocks.append(f"附表X.{i} 测试附表{i}")
            appendix_blocks.append(
                [
                    ["序号", "字段", "值"],
                    ["1", f"项目{i}", ""],
                ]
            )

        rfp_bytes = build_docx_blocks_bytes(*narrative_blocks, *appendix_blocks)

        deadline = time.monotonic()
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "大体量招标文件.docx",
                        rfp_bytes,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )
        elapsed = time.monotonic() - deadline

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        self.assertEqual(
            len(appendices),
            80,
            f"expected all 80 appendices to be discovered; got {len(appendices)}",
        )
        # 60s is a generous ceiling — the goal is to fail loudly if the
        # algorithm regresses (e.g. re-parsing the 20+ MB source per appendix
        # the way the first cut did, which took minutes per upload).
        self.assertLess(
            elapsed,
            60.0,
            f"appendix slicing took {elapsed:.1f}s for 5080-block / 80-appendix docx; "
            "suspect a regression in _slice_appendix_from_source caching",
        )

    def test_parse_docx_appendices_ignores_toc_titles_with_page_numbers(self) -> None:
        project_id = self.create_project()
        file_bytes = build_docx_blocks_bytes(
            "目录",
            "附表A.1 投标机型总方案信息表169",
            "附表B.1.2 机型配置品牌表1173",
            "附表B.9.1 双馈型风电机组179",
            "正文",
            "附表A.1 投标机型总方案信息表",
            [
                ["序号", "项目", "投标响应"],
                ["1", "总方案", ""],
            ],
            "附表B.1.2 机型配置品牌表1",
            [
                ["序号", "部件", "品牌"],
                ["1", "叶片", ""],
            ],
        )

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "含目录附表招标文件.docx",
                        file_bytes,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        self.assertEqual(
            [appendix["title"] for appendix in appendices],
            [
                "附表A.1 投标机型总方案信息表",
                "附表B.1.2 机型配置品牌表1",
            ],
        )
        self.assertEqual([appendix["id"] for appendix in appendices], ["APPX-0001", "APPX-0002"])
        self.assertEqual([appendix["rowCount"] for appendix in appendices], [2, 2])

    def test_markdown_appendix_heading_without_table_generates_workspace_docx(self) -> None:
        project_id = self.create_project()
        tender = "\n".join(
            [
                "# 招标文件",
                "项目名称：附表空表测试项目",
                "附表2：投标偏离表",
                "请投标人按招标文件要求填写。",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        self.assertEqual(len(appendices), 1)
        self.assertEqual(appendices[0]["status"], "generated")
        self.assertEqual(appendices[0]["rowCount"], 0)
        appendix_path = Path(appendices[0]["docxPath"])
        self.assertTrue(appendix_path.exists())
        self.assertEqual(appendices[0]["workspacePath"], f"s1_appendices/{appendix_path.name}")
        appendix_doc = Document(str(appendix_path))
        self.assertEqual(len(appendix_doc.tables), 0)
        self.assertIn("附表2：投标偏离表", [paragraph.text for paragraph in appendix_doc.paragraphs])

    def test_participating_promotes_parse_json_and_appendices_to_workspace(self) -> None:
        project_id = self.create_project()
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
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
        temp_appendix_path = Path(response.json()["structured"]["appendices"][0]["docxPath"])
        self.assertIn(str(settings.parsed_dir / project_id / "s1_appendices"), str(temp_appendix_path))
        temp_project_dir = settings.parsed_dir / project_id
        self.assertTrue(temp_project_dir.exists())
        stale_path = settings.documents_dir / project_id / "technical-workspace" / "appendices" / "stale.docx"
        stale_path.parent.mkdir(parents=True, exist_ok=True)
        stale_path.write_bytes(b"old")

        updated = self.client.put(
            self.project_url(project_id),
            json={
                "name": "参与后归档项目",
                "customerName": "测试业主",
                "manager": "项目经理",
                "startDate": "2026-01-01",
                "endDate": "2026-02-01",
                "bidType": "技术标",
                "reviewDecision": "participate",
            },
        )

        self.assertEqual(updated.status_code, 200)
        self.assertFalse(stale_path.exists())
        workspace_parse_dir = settings.documents_dir / project_id / "technical-workspace" / "parse"
        workspace_appendix_dir = settings.documents_dir / project_id / "technical-workspace" / "appendices"
        self.assertTrue((workspace_parse_dir / "s1_structured_result.json").exists())
        self.assertTrue((workspace_parse_dir / "parse-result.workspace.json").exists())
        workspace_appendices = sorted(workspace_appendix_dir.glob("*.docx"))
        self.assertEqual(len(workspace_appendices), 1)
        self.assertFalse(temp_project_dir.exists())

        promoted_payload = self.client.get(self.parse_results_url(project_id))
        self.assertEqual(promoted_payload.status_code, 200)
        appendix = promoted_payload.json()["structured"]["appendices"][0]
        self.assertIn(str(workspace_appendix_dir), appendix["docxPath"])
        self.assertEqual(appendix["workspacePath"], f"technical-workspace/appendices/{workspace_appendices[0].name}")

        project = store._require(project_id)
        parse_storage = project["parse_storage"]
        self.assertEqual(Path(parse_storage["projectDir"]), settings.documents_dir / project_id / "technical-workspace")
        self.assertEqual(Path(parse_storage["parseDir"]), workspace_parse_dir)
        self.assertEqual(Path(parse_storage["combinedTextPath"]), workspace_parse_dir / "combined.txt")
        self.assertEqual(Path(parse_storage["structuredResultPath"]), workspace_parse_dir / "s1_structured_result.json")
        self.assertEqual(Path(parse_storage["manifestPath"]), workspace_parse_dir / "manifest.json")
        self.assertEqual(Path(parse_storage["skillManifestPath"]), workspace_parse_dir / "s1_parse_manifest.json")
        self.assertTrue(all(str(workspace_parse_dir) in item["textPath"] for item in parse_storage["documents"]))

        preview = self.client.get(self.parse_results_url(project_id, "/appendices/APPX-0001/preview"))
        self.assertEqual(preview.status_code, 200)
        self.assertIn(str(workspace_appendix_dir), preview.json()["docxPath"])
        self.assertFalse(temp_project_dir.exists())

    def test_business_bid_parse_returns_business_contract_without_technical_groups(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：华能甘肃100MW风电项目",
                "招标编号：HN-BUS-2026-001",
                "招标人：华能集团",
                "交货周期：2026年10月1日至2027年3月31日",
                "质保期：5年",
                "附表3：商务评分标准表",
                "| 序号 | 评分项 | 分值 | 得分点 | 证明材料要求 |",
                "| --- | --- | --- | --- | --- |",
                "| 1 | 企业业绩 | 20分 | 近三年同类项目业绩满足要求得满分。 | 提供合同或中标通知书。 |",
                "投标函：按招标文件格式填写并签字盖章。",
                "法定代表人授权委托书：须加盖公章。",
                "商务偏差表：投标人应逐项响应。",
                "投标保证金：须提供电汇回单或保函。",
                "投标人证明其是合格投标人并有资格履行合同的证明文件。",
                "投标人不得存在下列情形之一。",
                "投标人需要说明的其他内容。",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        structured = payload["structured"]
        self.assertEqual(structured["schemaVersion"], "bid-business-tender-structured-v1")
        self.assertEqual(payload["summary"]["targetSkill"], "bid-business-tender-structured-parser")
        self.assertIn("commitmentLetterCount", payload["summary"])
        fact_by_key = {field["fieldKey"]: field for field in structured["projectFactFields"]}
        self.assertEqual(fact_by_key["projectName"]["value"], "华能甘肃100MW风电项目")
        self.assertEqual(fact_by_key["tenderNo"]["value"], "HN-BUS-2026-001")
        self.assertEqual(fact_by_key["tenderer"]["value"], "华能集团")

        field_groups = structured["fieldGroups"]
        self.assertIn("projectBasics", field_groups)
        self.assertIn("businessResponse", field_groups)
        self.assertIn("qualificationSupport", field_groups)
        self.assertIn("commitmentRequirements", field_groups)
        self.assertNotIn("turbineCoreParameters", field_groups)
        self.assertNotIn("performanceGuarantees", field_groups)
        self.assertNotIn("environmentAdaptation", field_groups)

        scoring = structured["scoringCriteria"]
        self.assertEqual(set(scoring.keys()), {"business", "price", "compliance"})
        self.assertGreaterEqual(len(scoring["business"]), 1)
        self.assertEqual(scoring["business"][0]["scoringItem"], "企业业绩")

        self.assertEqual(structured["requirementPresence"]["bidSecurity"]["status"], "present")
        self.assertEqual(structured["requirementPresence"]["qualificationDocuments"]["status"], "present")
        self.assertEqual(structured["requirementPresence"]["disqualificationClauses"]["status"], "present")

        commitment_fields = field_groups["commitmentRequirements"]
        self.assertEqual(field_by_key(commitment_fields, "generalCommitmentCount")["value"], "1")
        self.assertEqual(field_by_key(commitment_fields, "generatedCommitmentCount")["value"], "1")
        self.assertEqual(field_by_key(commitment_fields, "pendingCommitmentCount")["value"], "0")
        self.assertEqual(field_by_key(commitment_fields, "disqualificationCommitmentRequired")["status"], "found")

        letters = structured["commitmentLetters"]
        self.assertEqual(len(letters), 1)
        self.assertEqual(letters[0]["title"], "投标人不存在下列情形之一承诺函")
        self.assertEqual(letters[0]["commitmentType"], "disqualification")
        self.assertEqual(letters[0]["status"], "generated")
        self.assertTrue(letters[0]["docxPath"])
        self.assertTrue(Path(letters[0]["docxPath"]).exists())

        preview = self.client.get(
            self.parse_results_url(project_id, f"/commitment-letters/{letters[0]['id']}/preview")
        )
        self.assertEqual(preview.status_code, 200)
        preview_payload = preview.json()
        self.assertEqual(preview_payload["id"], letters[0]["id"])
        self.assertIn("/parse-results/commitment-letters/", preview_payload["onlyoffice"]["browserFileUrl"])

        approved = self.client.post(
            self.parse_results_url(project_id, f"/commitment-letters/{letters[0]['id']}/approve"),
            json={"approved": True},
        )
        self.assertEqual(approved.status_code, 200)
        approved_letter = approved.json()["letter"]
        self.assertEqual(approved_letter["assetReviewStatus"], "approved")
        self.assertEqual(approved_letter["assetMaterialFolder"], "02-商务响应文件")

    def test_business_bid_participating_promotes_parse_json_to_business_workspace(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：商务归档测试项目",
                "招标编号：BUS-2026-002",
                "投标保证金：须提交保函。",
                "投标人不得存在下列情形之一。",
                "附表1：商务偏差表",
                "| 序号 | 条款 | 偏差说明 |",
                "| --- | --- | --- |",
                "| 1 | 付款条件 | |",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["structured"]["schemaVersion"], "bid-business-tender-structured-v1")
        approve_response = self.client.post(
            self.parse_results_url(project_id, "/commitment-letters/approve"),
            json={"approved": True},
        )
        self.assertEqual(approve_response.status_code, 200)
        self.assertEqual(approve_response.json()["approvedCount"], 1)

        updated = self.client.put(
            self.project_url(project_id),
            json={
                "name": "商务归档测试项目",
                "customerName": "测试业主",
                "bidType": "商务标",
                "reviewDecision": "participate",
            },
        )
        self.assertEqual(updated.status_code, 200)

        workspace_parse_dir = settings.documents_dir / project_id / "business-workspace" / "parse"
        workspace_appendix_dir = settings.documents_dir / project_id / "business-workspace" / "appendices"
        workspace_commitment_dir = settings.documents_dir / project_id / "business-workspace" / "commitment-letters"
        self.assertTrue((workspace_parse_dir / "s1_structured_result.json").exists())
        self.assertTrue((workspace_parse_dir / "parse-result.workspace.json").exists())
        self.assertTrue(workspace_appendix_dir.exists())
        self.assertTrue(workspace_commitment_dir.exists())

        project = store._require(project_id)
        parse_storage = project["parse_storage"]
        self.assertEqual(Path(parse_storage["projectDir"]), settings.documents_dir / project_id / "business-workspace")
        self.assertEqual(Path(parse_storage["parseDir"]), workspace_parse_dir)

        structured_result = json.loads((workspace_parse_dir / "s1_structured_result.json").read_text(encoding="utf-8"))
        self.assertEqual(structured_result["schemaVersion"], "bid-business-tender-structured-v1")
        self.assertEqual(structured_result["structured"]["schemaVersion"], "bid-business-tender-structured-v1")
        commitment_letters = structured_result["structured"]["commitmentLetters"]
        self.assertEqual(len(commitment_letters), 1)
        self.assertIn(str(workspace_commitment_dir), commitment_letters[0]["docxPath"])
        self.assertEqual(
            commitment_letters[0]["workspacePath"],
            f"business-workspace/commitment-letters/{Path(commitment_letters[0]['docxPath']).name}",
        )

        preview = self.client.get(
            self.parse_results_url(project_id, f"/commitment-letters/{commitment_letters[0]['id']}/preview")
        )
        self.assertEqual(preview.status_code, 200)
        self.assertIn(str(workspace_commitment_dir), preview.json()["docxPath"])

    def test_business_bid_text_attachment_template_docx_keeps_template_body(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "第一章 投标文件格式",
                "附件1 投标函",
                "致：华能集团",
                "我方已仔细研究招标文件的全部内容，愿意按招标文件要求参加投标。",
                "投标人（盖章）：____________",
                "二、法定代表人授权书",
                "本人授权以下代表作为我方合法代理人参加本项目投标。",
                "授权代表签字：____________",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        self.assertGreaterEqual(len(appendices), 2)
        bid_letter = next(item for item in appendices if "投标函" in item["title"])
        self.assertEqual(bid_letter["rowCount"], 0)
        doc = Document(str(Path(bid_letter["docxPath"])))
        paragraph_texts = [paragraph.text for paragraph in doc.paragraphs]
        self.assertIn("致：华能集团", paragraph_texts)
        self.assertTrue(any("愿意按招标文件要求参加投标" in text for text in paragraph_texts))

    def test_business_bid_extracts_sixth_chapter_attachment_templates(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "第二章 投标人须知",
                "投标人须无条件承诺在本采购项目第一台合同设备供货前取得本条a和b所述材料，需提供承诺书。",
                "第六章 投标文件格式",
                "附件1 投标函",
                "致：华能集团",
                "投标人（盖章）：____________",
                "附件2 法定代表人（单位负责人）身份证明",
                "姓名：____________ 身份证号：____________",
                "附件3 业绩情况表",
                "| 序号 | 项目名称 | 合同容量 | 投运时间 |",
                "| --- | --- | --- | --- |",
                "| 1 |  |  |  |",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        structured = response.json()["structured"]
        appendices = structured["appendices"]
        titles = [item["title"] for item in appendices]
        self.assertTrue(any("附件1 投标函" in title for title in titles))
        self.assertTrue(any("法定代表人" in title and "身份证明" in title for title in titles))
        self.assertTrue(any("业绩情况表" in title for title in titles))
        bid_letter = next(item for item in appendices if "投标函" in item["title"])
        doc = Document(str(Path(bid_letter["docxPath"])))
        self.assertIn("致：华能集团", [paragraph.text for paragraph in doc.paragraphs])
        self.assertNotIn("投标人须无条件承诺", "".join(titles))

    def test_business_bid_docx_attachment_templates_are_sliced_with_quality_metadata(self) -> None:
        project_id = self.create_business_project()
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "商务附件模板招标文件.docx",
                        build_business_attachment_templates_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        titles = [item["title"] for item in appendices]
        self.assertEqual(
            titles,
            ["附件1 投标函", "附件2 开标价格表", "附件3 法定代表人授权书"],
        )

        bid_letter = appendices[0]
        self.assertEqual(bid_letter["artifactType"], "business_attachment_template")
        self.assertEqual(bid_letter["templateType"], "bid_letter")
        self.assertEqual(bid_letter["templateSectionTitle"], "第六章 投标文件格式")
        self.assertEqual(bid_letter["extractionMode"], "source_docx_slice")
        self.assertEqual(bid_letter["extractionQuality"], "complete")
        self.assertFalse(bid_letter["needsReview"])
        self.assertEqual(bid_letter["assetReviewStatus"], "pending_review")
        self.assertEqual(bid_letter["assetSyncStatus"], "pending")
        self.assertEqual(bid_letter["previewType"], "onlyoffice")
        self.assertIn("第六章 投标文件格式", bid_letter["sourceStart"])
        self.assertIn("附件2 开标价格表", bid_letter["sourceEnd"])

        bid_letter_doc = Document(str(Path(bid_letter["docxPath"])))
        bid_letter_text = "\n".join(paragraph.text for paragraph in bid_letter_doc.paragraphs)
        self.assertIn("附件1 投标函", bid_letter_text)
        self.assertIn("致：华能集团", bid_letter_text)
        self.assertIn("投标人（盖章）", bid_letter_text)
        self.assertNotIn("开标价格表", bid_letter_text)

        price_table = appendices[1]
        self.assertEqual(price_table["templateType"], "opening_price")
        self.assertEqual(price_table["extractionMode"], "source_docx_slice")
        self.assertEqual(price_table["extractionQuality"], "complete")
        price_docx_path = Path(price_table["docxPath"])
        with zipfile.ZipFile(price_docx_path) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
        self.assertIn("gridSpan", doc_xml)

    def test_business_bid_docx_attachment_templates_ignore_toc_and_keep_following_table(self) -> None:
        project_id = self.create_business_project()
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "商务附件模板含目录招标文件.docx",
                        build_business_attachment_templates_with_toc_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        titles = [item["title"] for item in appendices]
        self.assertEqual(
            titles,
            ["附件1 投标函", "附件3 货物规格一览表", "附件6 履约保证函格式承诺书和质量保函"],
        )
        self.assertFalse(any(title.endswith("111") for title in titles))

        spec_table = next(item for item in appendices if "货物规格" in item["title"])
        self.assertEqual(spec_table["templateType"], "specification")
        self.assertEqual(spec_table["extractionQuality"], "complete")
        spec_doc = Document(str(Path(spec_table["docxPath"])))
        self.assertEqual(len(spec_doc.tables), 1)
        self.assertEqual(spec_doc.tables[0].cell(0, 1).text, "货物名称")
        self.assertEqual(spec_doc.tables[0].cell(1, 1).text, "风力发电机组")

    def test_business_bid_docx_table_fingerprint_extracts_template_without_attachment_title(self) -> None:
        project_id = self.create_business_project()
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "商务表格指纹招标文件.docx",
                        build_business_fingerprint_only_tables_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        structured = response.json()["structured"]
        appendices = structured["appendices"]
        self.assertEqual([item["title"] for item in appendices], ["投标报价明细"])
        table_item = appendices[0]
        self.assertEqual(table_item["templateType"], "specification")
        self.assertEqual(table_item["extractionMode"], "source_docx_slice")
        self.assertEqual(table_item["tableFingerprint"]["type"], "specification")
        self.assertGreaterEqual(table_item["tableFingerprint"]["confidence"], 0.62)
        self.assertEqual(structured["businessFormatRegions"][0]["regionCount"], 1)
        table_doc = Document(str(Path(table_item["docxPath"])))
        self.assertEqual(len(table_doc.tables), 1)
        self.assertEqual(table_doc.tables[0].cell(1, 1).text, "风力发电机组")

    def test_business_bid_title_only_attachment_template_is_not_materialized(self) -> None:
        project_id = self.create_business_project()
        tender = build_docx_blocks_bytes(
            "第六章 投标文件格式",
            "附件1 投标函",
            "附件2 开标价格表",
            [
                ["序号", "项目名称", "投标报价"],
                ["1", "", ""],
            ],
        )

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "商务招标文件.docx",
                        tender,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        titles = [item["title"] for item in appendices]
        self.assertNotIn("附件1 投标函", titles)
        self.assertEqual(titles, ["附件2 开标价格表"])

    def test_business_bid_probably_incomplete_attachment_template_is_not_materialized(self) -> None:
        project_id = self.create_business_project()
        tender = build_docx_blocks_bytes(
            "第六章 投标文件格式",
            "附件1 其他说明",
            "本附件用于说明投标人认为需要说明的其他事项，具体内容由投标人结合项目实际情况自行说明",
            "附件2 开标价格表",
            [
                ["序号", "项目名称", "投标报价"],
                ["1", "", ""],
            ],
        )

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "商务招标文件.docx",
                        tender,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        titles = [item["title"] for item in appendices]
        self.assertNotIn("附件1 其他说明", titles)
        self.assertEqual(titles, ["附件2 开标价格表"])

    def test_business_bid_existing_commitment_template_suppresses_generated_duplicate(self) -> None:
        project_id = self.create_business_project()
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "商务承诺模板招标文件.docx",
                        build_business_commitment_template_alignment_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

        self.assertEqual(response.status_code, 200)
        structured = response.json()["structured"]
        appendices = structured["appendices"]
        self.assertEqual([item["title"] for item in appendices], ["附件1 材料取得承诺书"])
        self.assertEqual(structured["commitmentLetters"], [])
        alignments = structured["commitmentTemplateAlignments"]
        self.assertEqual(len(alignments), 1)
        self.assertEqual(alignments[0]["status"], "covered_by_existing_template")
        self.assertEqual(alignments[0]["matchedTemplateTitle"], "附件1 材料取得承诺书")

    def test_business_bid_unrelated_commitment_template_does_not_suppress_required_letter(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "投标人不得存在下列情形之一。",
                "# 第六章 投标文件格式",
                "附件6 履约保证函格式",
                "我方承诺按招标文件要求提交履约保证函。",
                "投标人（盖章）：____________",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        structured = response.json()["structured"]
        self.assertEqual([item["title"] for item in structured["appendices"]], ["附件6 履约保证函格式"])
        titles = [item["title"] for item in structured["commitmentLetters"]]
        self.assertIn("投标人不存在下列情形之一承诺函", titles)
        self.assertEqual(structured["commitmentTemplateAlignments"], [])

    def test_business_bid_generates_semantic_business_commitment_and_filters_technical_commitments(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：商务承诺优化项目",
                "招标编号：BUS-2026-COM-001",
                "招标人：测试招标人",
                "投标人需同时承诺两个保证年等效满负荷小时数值（需提供书面承诺函）。",
                "投标人保证年等效满负荷小时数（需提供书面承诺函）。",
                "投标人须无条件承诺在本采购项目第一台合同设备供货前取得本条a和b所述材料，需提供承诺书。",
                "投标人不得存在下列情形之一。",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        letters = response.json()["structured"]["commitmentLetters"]
        titles = [item["title"] for item in letters]
        all_text = "".join(titles + [str(item.get("triggerContext") or "") for item in letters])
        self.assertIn("材料取得承诺书", titles)
        self.assertIn("投标人不存在下列情形之一承诺函", titles)
        self.assertNotIn("等效满负荷小时", all_text)
        self.assertNotIn("发电量", all_text)

    def test_business_bid_commitment_semantic_review_can_override_strong_rule_candidate(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：商务承诺 AI 复核项目",
                "招标编号：BUS-2026-AI-001",
                "招标人：测试招标人",
                "投标人须无条件承诺在本采购项目第一台合同设备供货前取得本条a和b所述材料，需提供承诺书。",
            ]
        ).encode("utf-8")

        with patch.object(
            parsing_service.OpencodeClient,
            "review_business_commitments_with_trace",
            return_value={
                "decisions": [
                    {
                        "id": "RAW-0001",
                        "action": "ignore",
                        "topicKey": "certificate_obtainment",
                        "preferredTitle": "",
                        "reason": "AI 判断该项不需要自动生成商务承诺书。",
                    }
                ]
            },
        ) as mocked_review:
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_review.call_count, 1)
        self.assertEqual(response.json()["structured"]["commitmentLetters"], [])

    def test_business_bid_commitment_strong_rule_fallback_when_semantic_review_unavailable(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：商务承诺兜底项目",
                "招标编号：BUS-2026-FB-001",
                "招标人：测试招标人",
                "投标人须无条件承诺在本采购项目第一台合同设备供货前取得本条a和b所述材料，需提供承诺书。",
            ]
        ).encode("utf-8")

        with patch.object(
            parsing_service.OpencodeClient,
            "review_business_commitments_with_trace",
            side_effect=RuntimeError("semantic review unavailable"),
        ) as mocked_review:
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_review.call_count, 1)
        letters = response.json()["structured"]["commitmentLetters"]
        self.assertEqual([item["title"] for item in letters], ["材料取得承诺书"])
        self.assertIn("rule_fallback_generated", letters[0]["riskFlags"])

    def test_business_bid_commitment_titles_use_semantic_review_and_dedupe_same_topic(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：商务承诺测试项目",
                "招标编号：BUS-2026-SEM-001",
                "招标人：测试招标人",
                "第八章 投标人需要说明的其他内容",
                "保密承诺书",
                "本项仅为目录标题，不构成单独提交要求。",
                "另附保密承诺书。",
                "投标人须提供保密承诺书。",
                "保密承诺书",
                "投标人应提供保密承诺书。",
                "发电量承诺书另附。",
                "投标人不得存在下列情形之一。",
            ]
        ).encode("utf-8")

        with patch.object(
            parsing_service.OpencodeClient,
            "review_business_commitments_with_trace",
            return_value={
                "decisions": [
                    {
                        "id": "RAW-0001",
                        "action": "ignore",
                        "topicKey": "confidentiality",
                        "preferredTitle": "",
                        "reason": "仅标题，无明确单独提交要求。",
                    }
                ]
            },
        ) as mocked_review:
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        structured = payload["structured"]
        letters = structured["commitmentLetters"]
        titles = [item["title"] for item in letters]

        self.assertEqual(mocked_review.call_count, 1)
        self.assertEqual(len(letters), 2)
        self.assertEqual(titles.count("保密承诺书"), 1)
        self.assertIn("投标人不存在下列情形之一承诺函", titles)
        self.assertNotIn("发电量承诺书", "".join(titles))
        self.assertEqual(
            field_by_key(structured["fieldGroups"]["commitmentRequirements"], "generatedCommitmentCount")["value"],
            "2",
        )

    def test_business_bid_commitment_title_only_candidate_becomes_clue_when_semantic_review_uncertain(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：商务承诺线索测试项目",
                "招标编号：BUS-2026-SEM-002",
                "招标人：测试招标人",
                "第八章 投标人需要说明的其他内容",
                "保密承诺书",
                "本节为模板目录，具体内容见附件。",
            ]
        ).encode("utf-8")

        with patch.object(
            parsing_service.OpencodeClient,
            "review_business_commitments_with_trace",
            return_value={
                "decisions": [
                    {
                        "id": "RAW-0001",
                        "action": "clue",
                        "topicKey": "confidentiality",
                        "preferredTitle": "",
                        "reason": "仅识别到标题，建议人工确认是否需要单独成文。",
                    }
                ]
            },
        ) as mocked_review:
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        structured = payload["structured"]
        self.assertEqual(mocked_review.call_count, 1)
        self.assertEqual(structured["commitmentLetters"], [])
        self.assertEqual(len(structured["commitmentClues"]), 1)
        self.assertEqual(structured["commitmentClues"][0]["topicKey"], "confidentiality")
        self.assertIn("人工确认", structured["commitmentClues"][0]["recommendedAction"])
        self.assertEqual(
            field_by_key(structured["fieldGroups"]["commitmentRequirements"], "pendingCommitmentCount")["value"],
            "1",
        )

    def test_delete_project_cleans_parse_temp_workspace(self) -> None:
        project_id = self.create_project()
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
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
        temp_project_dir = settings.parsed_dir / project_id
        self.assertTrue(temp_project_dir.exists())

        deleted = self.client.delete(self.project_url(project_id))

        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(temp_project_dir.exists())

    def test_delete_business_project_cleans_project_material_folder(self) -> None:
        project_id = self.create_business_project()
        deleted_paths: list[str] = []

        def fake_delete_folder(path: str) -> dict[str, object]:
            deleted_paths.append(path)
            return {"message": "deleted", "folderPath": path, "deletedFileCount": 2}

        with patch("app.services.bid_project_state.run_workspace_material_folder_delete", side_effect=fake_delete_folder):
            deleted = self.client.delete(self.project_url(project_id))

        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted_paths, [f"商务标/项目素材/{project_id}"])

    def test_parse_results_materializes_legacy_required_appendix_preview_docx(self) -> None:
        project_id = self.create_project()
        complete_parse_for_tests(
            project_id,
            [{"id": "TEN-1", "name": "招标文件.docx", "size_label": "1.0 MB"}],
            [],
            summary={"fileCount": 1, "extractedCount": 0, "textLength": 0, "warnings": []},
            parse_storage={
                "items": [],
                "structured": {
                    "appendices": [
                        {
                            "id": "APPX-0007",
                            "title": "附表7：技术资料递交表",
                            "status": "required_no_template",
                            "sourceFile": "招标文件.docx",
                            "evidence": "附表7：技术资料递交表",
                            "evidenceLocation": "L88",
                            "rows": [],
                            "rowCount": 0,
                            "docxPath": "",
                        }
                    ]
                },
            },
        )

        response = self.client.get(self.parse_results_url(project_id))
        self.assertEqual(response.status_code, 200)
        appendix = response.json()["structured"]["appendices"][0]
        self.assertEqual(appendix["status"], "generated")
        self.assertEqual(appendix["rowCount"], 0)
        appendix_path = Path(appendix["docxPath"])
        self.assertTrue(appendix_path.exists())

        preview = self.client.get(self.parse_results_url(project_id, "/appendices/APPX-0007/preview"))
        self.assertEqual(preview.status_code, 200)
        preview_payload = preview.json()
        self.assertEqual(preview_payload["id"], "APPX-0007")
        self.assertEqual(preview_payload["onlyoffice"]["documentType"], "word")
        self.assertTrue(preview_payload["onlyoffice"]["documentKey"])

        file_response = self.client.get(
            self.parse_results_url(project_id, f"/appendices/APPX-0007/file/{appendix_path.name}")
        )
        self.assertEqual(file_response.status_code, 200)
        self.assertGreater(len(file_response.content), 0)

    def test_parse_progress_records_real_steps_and_completion(self) -> None:
        project_id = self.create_project()
        tender = "项目名称：进度测试项目\n单机容量：6.25MW\n".encode("utf-8")

        before = self.client.get(self.parse_results_url(project_id, "/progress"))
        self.assertEqual(before.status_code, 200)
        self.assertEqual(before.json()["status"], "idle")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("招标文件.md", tender, "text/markdown"))],
        )
        self.assertEqual(response.status_code, 200)

        progress = self.client.get(self.parse_results_url(project_id, "/progress"))
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
            "/api/technical/projects",
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
            f"/api/technical/projects/{created['id']}",
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

        list_response = self.client.get("/api/technical/projects")
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
            self.parse_results_url(project_id, "/upload-and-run"),
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
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    ("招标文件.docx", tender_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                )
            ],
        )
        self.assertEqual(first_response.status_code, 200)

        second_response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
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

    def test_parse_inputs_do_not_use_legacy_template_when_project_has_no_template(self) -> None:
        project_id = self.create_project()
        tender_bytes = build_docx_bytes("招标文件正文", "项目概况", "项目没有单独上传投标模板。")
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    ("招标文件.docx", tender_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                )
            ],
        )
        self.assertEqual(response.status_code, 200)

        with patch("app.services.template_store.resolve_system_default_bid_template_file", return_value=None):
            _, template_files = parse_inputs_for_tests(project_id)

        self.assertEqual(template_files, [])

    def test_parse_inputs_use_settings_default_template_when_project_has_no_template(self) -> None:
        project_id = self.create_project()
        tender_bytes = build_docx_bytes("招标文件正文", "项目概况", "项目没有单独上传投标模板。")
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    ("招标文件.docx", tender_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                )
            ],
        )
        self.assertEqual(response.status_code, 200)

        default_path = settings.uploads_dir / project_id / "system-default-template" / "默认技术标模板.docx"
        default_path.parent.mkdir(parents=True, exist_ok=True)
        default_path.write_bytes(build_docx_bytes("默认技术标模板", "第一章 模板章节"))
        default_record = {
            "id": "TPL-0001",
            "name": "默认技术标模板.docx",
            "stored_name": "默认技术标模板.docx",
            "size_bytes": default_path.stat().st_size,
            "size_label": format_size_mb(default_path.stat().st_size),
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "path": str(default_path),
            "source": "system-default",
            "isFallback": True,
            "templateType": "technical",
            "templateTypeLabel": "技术标",
            "minioBucket": "bid-templates",
            "minioKey": "templates/default/technical/default-template.docx",
        }

        with patch("app.services.template_store.resolve_system_default_bid_template_file", return_value=default_record):
            _, template_files = parse_inputs_for_tests(project_id)

        self.assertEqual(len(template_files), 1)
        self.assertEqual(template_files[0]["name"], "默认技术标模板.docx")
        self.assertEqual(template_files[0]["source"], "system-default")
        self.assertEqual(template_files[0]["templateType"], "technical")

    def test_project_template_overrides_fallback_template(self) -> None:
        project_id = self.create_project()
        tender_bytes = build_docx_bytes("招标文件正文", "项目概况", "项目后续上传自己的投标模板。")
        template_bytes = build_docx_bytes("项目投标模板", "第一章 项目模板章节")
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
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

        default_record = {
            "id": "TPL-0001",
            "name": "默认技术标模板.docx",
            "path": "/tmp/default-template.docx",
            "source": "system-default",
            "isFallback": True,
        }
        with patch("app.services.template_store.resolve_system_default_bid_template_file", return_value=default_record):
            _, template_files = parse_inputs_for_tests(project_id)

        self.assertEqual(len(template_files), 1)
        self.assertEqual(template_files[0]["name"], "项目模板.docx")
        self.assertNotEqual(template_files[0].get("source"), "system-default")


if __name__ == "__main__":
    unittest.main()
