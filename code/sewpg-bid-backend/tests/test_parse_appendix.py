from __future__ import annotations

import json
import threading
import time
import zipfile
from pathlib import Path
from unittest.mock import patch
from docx import Document
from app.core.config import settings
from app.services import parsing as parsing_service

from parse_pipeline_helpers import (
    ParsePipelineTestBase,
    build_appendix_docx_bytes,
    build_appendix_with_merges_docx_bytes,
    build_docx_blocks_bytes,
    field_by_key,
)


class ParsePipelineTests(ParsePipelineTestBase):

    def test_technical_appendix_extraction_runs_concurrently_with_structured_parse(self) -> None:
        """附表提取与 opencode 会话之间没有依赖，必须并行。

        串行时这段本地耗时（真实项目实测 105 秒）会白白排在会话前面；
        两个事件互等，只有真正并行才能同时满足，串行会在这里等超时。
        """
        project_id = self.create_project()
        tender_path = settings.uploads_dir / project_id / "tender.docx"
        tender_path.parent.mkdir(parents=True, exist_ok=True)
        tender_path.write_bytes(
            build_docx_blocks_bytes(
                "附表A.1 投标机型总方案信息表",
                [["序号", "项目", "投标响应"], ["1", "机型总方案", ""]],
            )
        )

        skill_started = threading.Event()
        appendix_started = threading.Event()
        observed: dict[str, bool] = {}

        def fake_extract_docx_appendices(*args, **kwargs):
            appendix_started.set()
            observed["skillStartedWhileExtracting"] = skill_started.wait(timeout=10)
            return []

        def fake_run_parse_skill(_manifest_path, *, local_result, profile, progress_callback=None, cancel_check=None):
            skill_started.set()
            observed["appendixRunningWhenSkillStarted"] = appendix_started.wait(timeout=10)
            return local_result, ""

        with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
            "app.services.parsing._extract_docx_appendices",
            side_effect=fake_extract_docx_appendices,
        ), patch(
            "app.services.parsing._run_parse_skill",
            side_effect=fake_run_parse_skill,
        ):
            parsing_service.parse_tender_documents(
                project_id,
                [
                    {
                        "id": "DOC-1",
                        "name": "tender.docx",
                        "path": str(tender_path),
                        "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    }
                ],
                bid_type="技术标",
            )

        self.assertTrue(observed.get("skillStartedWhileExtracting"), "结构化解析必须在附表提取完成前就已启动")
        self.assertTrue(observed.get("appendixRunningWhenSkillStarted"), "附表提取必须在结构化解析启动时已在跑")



    def test_technical_appendix_failure_is_not_swallowed_by_a_successful_skill_run(self) -> None:
        """附表分支在后台线程里失败时必须显式抛出，不能因为会话成功就当整体成功。"""
        project_id = self.create_project()
        tender_path = settings.uploads_dir / project_id / "tender-fail.docx"
        tender_path.parent.mkdir(parents=True, exist_ok=True)
        tender_path.write_bytes(build_docx_blocks_bytes("附表A.1 投标机型总方案信息表"))

        def boom(*args, **kwargs):
            raise RuntimeError("附表提取炸了")

        with patch("app.services.parsing.settings.s1_parse_opencode_enabled", True), patch(
            "app.services.parsing._extract_docx_appendices",
            side_effect=boom,
        ), patch(
            "app.services.parsing._run_parse_skill",
            side_effect=lambda _p, *, local_result, **kwargs: (local_result, ""),
        ):
            with self.assertRaisesRegex(RuntimeError, "附表提取炸了"):
                parsing_service.parse_tender_documents(
                    project_id,
                    [
                        {
                            "id": "DOC-1",
                            "name": "tender-fail.docx",
                            "path": str(tender_path),
                            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        }
                    ],
                    bid_type="技术标",
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
        self.assertEqual(
            [field["key"] for field in project_basics],
            ["projectName", "tenderNo", "projectUnit", "tenderer", "tenderAgency", "bidDeadline"],
        )
        self.assertTrue(all(field["value"] == "" for field in project_basics))

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



    def test_parse_pdf_text_appendix_generates_workspace_docx(self) -> None:
        project_id = self.create_project()
        tender_text = "\n".join(
            [
                "招标文件技术规范",
                "附表G.3.1 关键设计方法 ..................................................206",
                "附表G.2.4 场址投标机组疲劳载荷与认证机组疲劳载荷对比（m=10）206",
                "附表G.5.2 招标项目场址机组等效疲劳载荷与认证机组等效疲劳载荷对",
                "比 ................................................................................................................. 209",
                "附表G.3.2 塔筒极限强度设计安全余量",
                "序号 截面位置 安全余量 投标响应",
                "1 塔底 不低于5% ",
                "2 门洞 不低于5% ",
                "附表G.3.3 塔筒屈曲稳定性安全余量",
                "序号 截面位置 安全余量 投标响应",
                "1 塔底 不低于5% ",
            ]
        )

        def fake_extract_pdf_text(_path: Path):
            return tender_text, {"pageCount": 3, "warnings": [], "requiresOcr": False}

        with patch("app.services.parsing.settings.business_pdf_parse_engine", "lightweight", create=True), patch(
            "app.services.parsing.extract_pdf_text",
            side_effect=fake_extract_pdf_text,
        ):
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("招标文件-技术规范.pdf", b"%PDF-1.4\n", "application/pdf"))],
            )

        self.assertEqual(response.status_code, 200)
        appendices = response.json()["structured"]["appendices"]
        self.assertEqual([item["title"] for item in appendices], ["附表G.3.2 塔筒极限强度设计安全余量", "附表G.3.3 塔筒屈曲稳定性安全余量"])
        self.assertEqual([item["rowCount"] for item in appendices], [3, 2])
        appendix_doc = Document(appendices[0]["docxPath"])
        self.assertEqual(len(appendix_doc.tables), 1)
        self.assertEqual(appendix_doc.tables[0].cell(0, 1).text, "截面位置")
        self.assertEqual(appendix_doc.tables[0].cell(1, 3).text, "")



    def test_parse_pdf_document_nav_appendix_preserves_table_blocks(self) -> None:
        project_id = self.create_project()
        nav_payload = {
            "schemaVersion": "business-document-nav-v1",
            "sourceEngine": "docling",
            "documents": [{"id": "DOC-1", "sourcePath": "technical.pdf"}],
            "pages": [{"pageNo": page_no, "textDensity": 0.8} for page_no in range(1, 556)],
            "blocks": [
                {"id": "DOC-1:B000001", "type": "paragraph", "text": "招标文件技术规范", "pageNo": 1},
                {"id": "DOC-1:B000002", "type": "heading", "text": "附表A.1 投标机型总方案信息表", "pageNo": 1, "bbox": [50, 80, 500, 110]},
                {"id": "DOC-1:B000003", "type": "paragraph", "text": "投标人应按下表填写。", "pageNo": 1, "bbox": [50, 120, 500, 145]},
                {"id": "DOC-1:B000004", "type": "table", "text": "", "tableId": "T1", "pageNo": 1, "bbox": [50, 150, 540, 260]},
                {"id": "DOC-1:B000005", "type": "heading", "text": "附表A.2 机型配置品牌表", "pageNo": 2, "bbox": [50, 80, 500, 110]},
                {"id": "DOC-1:B000006", "type": "table", "text": "", "tableId": "T2", "pageNo": 2, "bbox": [50, 150, 540, 230]},
            ],
            "tables": [
                {
                    "id": "T1",
                    "rows": [
                        ["编号", "项目", "", "备注"],
                        ["12", "塔筒重量（t）", "TG1", "说明"],
                        ["", "", "TG2", ""],
                    ],
                    "cells": [
                        {"rowStart": 0, "rowEnd": 1, "colStart": 0, "colEnd": 1, "rowSpan": 1, "colSpan": 1, "text": "编号", "bbox": []},
                        {"rowStart": 0, "rowEnd": 1, "colStart": 1, "colEnd": 3, "rowSpan": 1, "colSpan": 2, "text": "项目", "bbox": []},
                        {"rowStart": 0, "rowEnd": 1, "colStart": 3, "colEnd": 4, "rowSpan": 1, "colSpan": 1, "text": "备注", "bbox": []},
                        {"rowStart": 1, "rowEnd": 3, "colStart": 0, "colEnd": 1, "rowSpan": 2, "colSpan": 1, "text": "12", "bbox": []},
                        {"rowStart": 1, "rowEnd": 3, "colStart": 1, "colEnd": 2, "rowSpan": 2, "colSpan": 1, "text": "塔筒重量（t）", "bbox": []},
                        {"rowStart": 1, "rowEnd": 2, "colStart": 2, "colEnd": 3, "rowSpan": 1, "colSpan": 1, "text": "TG1", "bbox": []},
                        {"rowStart": 1, "rowEnd": 3, "colStart": 3, "colEnd": 4, "rowSpan": 2, "colSpan": 1, "text": "说明", "bbox": []},
                        {"rowStart": 2, "rowEnd": 3, "colStart": 2, "colEnd": 3, "rowSpan": 1, "colSpan": 1, "text": "TG2", "bbox": []},
                    ],
                    "sourceEngine": "docling",
                },
                {
                    "id": "T2",
                    "rows": [
                        ["序号", "部件", "品牌"],
                        ["1", "叶片", ""],
                    ],
                    "sourceEngine": "docling",
                },
            ],
            "images": [],
            "evidence": [],
            "quality": {"engine": "docling", "status": "completed", "fallbackUsed": False},
        }

        def fake_parse_pdf(self, *, project_id: str, document: dict, output_dir: Path):
            nav_path = output_dir / "DOC-1_document_nav.json"
            quality_path = output_dir / "document_parse" / "docling" / "DOC-1" / "parse_quality.json"
            quality_path.parent.mkdir(parents=True, exist_ok=True)
            nav_path.write_text(json.dumps(nav_payload, ensure_ascii=False), encoding="utf-8")
            quality_path.write_text(
                json.dumps({"engine": "docling", "status": "completed", "fallbackUsed": False}, ensure_ascii=False),
                encoding="utf-8",
            )
            return {
                "documentParseEngine": "docling",
                "status": "completed",
                "documentNavPath": str(nav_path),
                "parseQualityPath": str(quality_path),
            }

        with patch("app.services.parsing.settings.business_pdf_parse_engine", "docling", create=True), patch(
            "app.services.parsing.DoclingParseEngine.parse_pdf",
            new=fake_parse_pdf,
        ), patch(
            "app.services.parsing.extract_pdf_text",
            side_effect=AssertionError("技术标 DocumentNav 已包含全文，不应重复扫描 PDF"),
        ):
            response = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("招标文件-技术规范.pdf", b"%PDF-1.4\n", "application/pdf"))],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sourceFiles"][0]["pageCount"], 555)
        self.assertEqual(response.json()["sourceFiles"][0]["textLength"], len(parsing_service.nav_to_text(nav_payload)))
        appendices = response.json()["structured"]["appendices"]
        self.assertEqual(
            [item["title"] for item in appendices],
            ["附表A.1 投标机型总方案信息表", "附表A.2 机型配置品牌表"],
        )
        self.assertEqual([item["extractionMode"] for item in appendices], ["pdf_document_nav_slice", "pdf_document_nav_slice"])
        self.assertEqual([item["rowCount"] for item in appendices], [3, 2])
        self.assertEqual(appendices[0]["sourceEngine"], "docling")
        self.assertEqual(appendices[0]["sourceStart"], "P1")
        self.assertEqual(appendices[0]["contentBlocks"][1]["cells"][1]["colSpan"], 2)
        self.assertEqual(appendices[0]["contentBlocks"][1]["cells"][3]["rowSpan"], 2)
        appendix_doc = Document(appendices[0]["docxPath"])
        self.assertEqual(len(appendix_doc.tables), 1)
        self.assertEqual(appendix_doc.tables[0].cell(0, 1).text, "项目")
        self.assertEqual(appendix_doc.tables[0].cell(1, 1).text, "塔筒重量（t）")
        with zipfile.ZipFile(appendices[0]["docxPath"]) as docx_zip:
            document_xml = docx_zip.read("word/document.xml").decode("utf-8")
        self.assertIn("gridSpan", document_xml)
        self.assertIn("vMerge", document_xml)



    def test_technical_pdf_docling_failure_does_not_use_local_table_nav_fallback(self) -> None:
        project_id = self.create_project()
        pdf_path = settings.uploads_dir / project_id / "technical.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4\n")

        def fake_run_docling_conversion(_pdf_path: Path, _output_dir: Path):
            raise RuntimeError("rapidocr model missing")

        with patch("app.services.parsing.settings.s1_parse_opencode_enabled", False), patch(
            "app.services.parsing.settings.business_pdf_parse_engine",
            "docling",
            create=True,
        ), patch(
            "app.services.parsing.settings.business_pdf_engine_fallback",
            "none",
            create=True,
        ), patch(
            "app.services.docling_engine.run_docling_conversion",
            side_effect=fake_run_docling_conversion,
        ), patch(
            "app.services.docling_engine.run_docling_local_text_layer_conversion",
            side_effect=AssertionError("technical PDF must not use local-text-layer fallback"),
        ), patch(
            "app.services.parsing.extract_pdf_text",
            return_value=("技术标全文正文", {"pageCount": 1, "warnings": [], "requiresOcr": False}),
        ):
            _summary, storage = parsing_service.parse_tender_documents(
                project_id,
                [
                    {
                        "id": "DOC-1",
                        "name": "招标文件-技术规范.pdf",
                        "path": str(pdf_path),
                        "content_type": "application/pdf",
                    }
                ],
                bid_type="技术标",
            )

        self.assertEqual(storage["structured"]["appendices"], [])
        self.assertEqual(storage["documents"][0]["documentParseStatus"], "failed")
        self.assertIn("rapidocr model missing", storage["documents"][0]["fallbackReason"])



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



    def test_technical_docx_plain_tables_skip_source_slice_but_merged_tables_keep_it(self) -> None:
        plain_path = settings.uploads_dir / "plain-appendix.docx"
        merged_path = settings.uploads_dir / "merged-appendix.docx"
        plain_path.write_bytes(
            build_docx_blocks_bytes(
                "附表A.1 投标机型总方案信息表",
                [
                    ["序号", "项目", "投标响应"],
                    ["1", "机型总方案", ""],
                ],
            )
        )
        merged_path.write_bytes(build_appendix_with_merges_docx_bytes())

        captured: list[dict] = []

        def fake_materialize(project_id: str, appendix: dict, *, profile):
            captured.append(appendix)
            return dict(appendix)

        with patch("app.services.parse_appendix.materialize_appendix_docx", side_effect=fake_materialize):
            parsing_service._extract_docx_appendices(
                "PRJ-SLICE-POLICY",
                [
                    {"name": "plain-appendix.docx", "sourcePath": str(plain_path)},
                    {"name": "merged-appendix.docx", "sourcePath": str(merged_path)},
                ],
            )

        self.assertEqual(len(captured), 2)
        self.assertNotIn("_slice", captured[0])
        self.assertIn("_slice", captured[1])



    def test_large_docx_slice_stores_document_xml_without_expensive_deflate(self) -> None:
        source_path = settings.uploads_dir / "large-slice-source.docx"
        target_path = settings.parsed_dir / "large-slice-target.docx"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        doc = Document()
        doc.add_paragraph("附表A.1 大型测试表")
        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "序号"
        table.cell(0, 1).text = "内容"
        table.cell(1, 0).text = "1"
        table.cell(1, 1).text = "大段内容" * 20
        doc.save(source_path)

        source_state = parsing_service._build_appendix_slice_state(source_path)
        with patch("app.services.parse_appendix.DOCX_SLICE_STORED_XML_THRESHOLD_BYTES", 1, create=True):
            sliced = parsing_service._slice_appendix_from_source(
                source_path,
                target_path,
                0,
                1,
                source_state=source_state,
            )

        self.assertTrue(sliced)
        with zipfile.ZipFile(target_path) as zf:
            self.assertEqual(zf.getinfo("word/document.xml").compress_type, zipfile.ZIP_STORED)



    def test_large_rebuilt_appendix_table_writes_within_budget(self) -> None:
        target_path = settings.parsed_dir / "large-rebuilt-appendix-table.docx"
        rows = [
            [f"R{row_index}C{column_index} " * 2 for column_index in range(5)]
            for row_index in range(160)
        ]

        started_at = time.perf_counter()
        parsing_service._write_appendix_docx(
            target_path,
            "技术附表I 技术条款偏差表",
            rows,
            [{"type": "table", "rows": rows}],
        )
        elapsed = time.perf_counter() - started_at

        self.assertLess(elapsed, 4.0)
        doc = Document(str(target_path))
        self.assertEqual(len(doc.tables), 1)
        self.assertEqual(len(doc.tables[0].rows), len(rows))
        self.assertEqual(doc.tables[0].cell(159, 4).text, rows[159][4])



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
