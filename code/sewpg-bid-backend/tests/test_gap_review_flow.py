from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services.store import now_iso, store
from app.services.workspace_artifacts import technical_workspace_dir


class GapReviewFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.ensure_dirs()

        store.reset_for_tests()
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")
        self.gap_planner_patcher = patch(
            "app.services.gap_planning.OpencodeClient.run_bid_tech_gap_planner_with_trace",
            side_effect=RuntimeError("offline test fallback"),
        )
        self.gap_planner_mock = self.gap_planner_patcher.start()

    def tearDown(self) -> None:
        self.gap_planner_patcher.stop()
        self.client.close()
        self.temp_dir.cleanup()

    def _create_project_with_confirmed_outline(self) -> str:
        response = self.client.post(
            "/api/projects",
            json={
                "name": "S4-S6联调项目",
                "customerName": "测试业主",
            },
        )
        response.raise_for_status()
        project_id = response.json()["id"]

        store.save_generated_outline(
            project_id=project_id,
            nodes=[
                {
                    "id": "OL-1",
                    "title": "第1章 标前概述",
                    "children": [
                        {"id": "OL-1-1", "title": "技术评分标准索引表", "children": []},
                        {"id": "OL-1-2", "title": "投标方案优势说明", "children": []},
                    ],
                },
                {
                    "id": "OL-2",
                    "title": "第2章 技术标准",
                    "children": [
                        {"id": "OL-2-1", "title": "性能保证", "children": []},
                    ],
                },
                {
                    "id": "OL-3",
                    "title": "第3章 风资源评估与机位排布方案",
                    "children": [],
                },
            ],
            generated_at=now_iso(),
            summary="目录已生成。",
        )
        store.confirm_outline(project_id)
        return project_id

    def _create_project_with_confirmed_directory_json(self) -> str:
        project_id = self._create_project_with_confirmed_outline()
        project_dir = technical_workspace_dir(project_id)
        work_dir = project_dir / "s2_toc_workdir"
        work_dir.mkdir(parents=True, exist_ok=True)
        toc_json = work_dir / "投标文件-总目录.json"
        toc_json.write_text(
            json.dumps(
                {
                    "schema_version": "bid-toc-json-v1",
                    "document_title": "S4-S6联调项目投标文件总目录",
                    "project": {
                        "owner": "测试业主",
                        "name": "S4-S6联调项目",
                        "code": project_id,
                    },
                    "items": [
                        {
                            "order": 1,
                            "number": "1",
                            "title": "标前概述",
                            "level": 1,
                            "annotation": "保留",
                            "source": "template",
                            "reason": "",
                            "material_refs": [],
                        },
                        {
                            "order": 2,
                            "number": "1.1",
                            "title": "技术评分标准索引表",
                            "level": 2,
                            "annotation": "适配",
                            "source": "wiki",
                            "reason": "匹配素材库：评分索引",
                            "material_refs": [
                                {
                                    "id": "RAW-0001",
                                    "docx": "技术标/通用素材/技术评分标准索引表.docx",
                                    "usage": "both",
                                }
                            ],
                        },
                        {
                            "order": 3,
                            "number": "2.1",
                            "title": "性能保证",
                            "level": 2,
                            "annotation": "新增-招标要求",
                            "source": "tender_special",
                            "reason": "招标文件要求填写性能保证附表",
                            "material_refs": [],
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        parse_storage = store.get_parse_storage(project_id)
        parse_storage["projectDir"] = str(project_dir)
        project = store._require(project_id)
        project["parse_storage"] = parse_storage
        project["parse_result"]["structured"] = {
            "appendices": [
                {
                    "id": "APP-PERF",
                    "title": "性能保证附表",
                    "sourceFile": "招标文件.docx",
                    "blankTable": True,
                }
            ],
            "projectDates": {"startDate": "2026-06-01", "endDate": "2026-09-30"},
        }
        store._persist_project(project)
        return project_id

    def test_gap_detection_creates_real_gap_plan_from_directory_material_refs_and_parse_appendices(self) -> None:
        project_id = self._create_project_with_confirmed_directory_json()

        response = self.client.post(f"/api/projects/{project_id}/gaps-detection/run")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertIn("gapPlan", payload)
        self.assertEqual(payload["gapPlan"]["schemaVersion"], "bid-tech-gap-plan-v1")
        self.assertEqual(payload["summary"]["totalTocItems"], 3)
        self.assertEqual(payload["summary"]["matchedCount"], 1)
        self.assertEqual(payload["summary"]["missingCount"], 1)
        self.assertGreaterEqual(payload["summary"]["fillableTaskCount"], 1)
        matched = next(item for item in payload["gapPlan"]["items"] if item["status"] == "matched")
        self.assertEqual(matched["matchedMaterials"][0]["id"], "RAW-0001")
        missing = next(item for item in payload["gapPlan"]["items"] if item["status"] == "needs_input")
        self.assertEqual(missing["number"], "2.1")
        self.assertEqual(missing["fillTasks"][0]["skill"], "bid-tech-table-filler")
        self.assertTrue(payload["gapPlan"]["planFile"].endswith("gap_plan.json"))
        self.gap_planner_mock.assert_called_once()
        planner_prompt = self.gap_planner_mock.call_args.args[0]
        self.assertIn("Use the bid-tech-gap-planner skill", planner_prompt)
        self.assertIn("s4gap", planner_prompt)

    def test_gap_ai_fill_calls_opencode_skill_and_registers_resolved_artifact(self) -> None:
        project_id = self._create_project_with_confirmed_directory_json()
        detection_response = self.client.post(f"/api/projects/{project_id}/gaps-detection/run")
        self.assertEqual(detection_response.status_code, 200)
        gap_plan = detection_response.json()["gapPlan"]
        fill_item = next(item for item in gap_plan["items"] if item["fillTasks"])
        gap_id = fill_item["id"]
        fill_task_id = fill_item["fillTasks"][0]["id"]

        def fake_run_table_filler(manifest_path, progress_callback=None):
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            output_file = Path(manifest["outputFile"])
            output_file.parent.mkdir(parents=True, exist_ok=True)
            doc = Document()
            doc.add_paragraph("性能保证附表")
            doc.add_paragraph("已根据参考素材和解析字段填写。")
            doc.save(output_file)
            return {
                "schema_version": "bid-tech-table-fill-v1",
                "outputFile": str(output_file),
                "unfilledFields": ["保证值来源页码"],
                "evidenceRefs": [{"source": "招标文件.docx", "field": "性能保证"}],
                "opencodeOutput": {
                    "status": "received",
                    "sessionId": str(manifest_path),
                    "providerId": "local-skill",
                    "modelId": "bid-tech-table-filler",
                    "receivedAt": "2026-05-02T00:00:00Z",
                    "parts": [{"type": "text", "text": "{\"schema_version\":\"bid-tech-table-fill-v1\"}"}],
                },
            }

        with patch(
            "app.services.gap_planning.run_table_filler_skill",
            side_effect=fake_run_table_filler,
        ):
            response = self.client.post(
                f"/api/projects/{project_id}/gaps/{gap_id}/ai-fill",
                json={
                    "fillTaskId": fill_task_id,
                    "referenceMaterialIds": ["RAW-0001"],
                    "parseFieldIds": ["APP-PERF"],
                    "operator": "测试用户",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["item"]["status"], "resolved")
        self.assertEqual(payload["artifact"]["source"], "ai_fill")
        self.assertEqual(payload["artifact"]["skill"], "bid-tech-table-filler")
        self.assertTrue(Path(payload["artifact"]["path"]).exists())
        self.assertIn("onlyoffice", payload["artifact"])
        updated_gap = self.client.get(f"/api/projects/{project_id}/gaps").json()["gapPlan"]
        updated_item = next(item for item in updated_gap["items"] if item["id"] == gap_id)
        self.assertEqual(updated_item["resolvedArtifacts"][0]["source"], "ai_fill")
        self.assertEqual(updated_item["fillTasks"][0]["status"], "completed")

    def test_gap_ai_fill_manifest_carries_appendix_context_and_recommended_materials(self) -> None:
        project_id = self._create_project_with_confirmed_directory_json()
        project = store._require(project_id)
        project["parse_result"]["structured"]["appendices"][0]["availableParseFields"] = [
            {"id": "FIELD-POWER", "label": "单机容量", "value": "10MW", "sourceFile": "招标文件.docx"},
            {"id": "FIELD-ROTOR", "label": "叶轮直径", "value": "220m", "sourceFile": "招标文件.docx"},
        ]
        store._persist_project(project)
        detection_response = self.client.post(f"/api/projects/{project_id}/gaps-detection/run")
        self.assertEqual(detection_response.status_code, 200)
        gap_plan = detection_response.json()["gapPlan"]
        fill_item = next(item for item in gap_plan["items"] if item["fillTasks"])
        gap_id = fill_item["id"]
        fill_task_id = fill_item["fillTasks"][0]["id"]
        fill_item["appendixTasks"][0]["recommendedMaterials"] = [
            {
                "id": "RAW-0001",
                "name": "性能保证基准素材.docx",
                "folderPath": "技术标/通用素材",
                "materialTier": "standard",
                "usage": "table_source",
            }
        ]
        project = store._require(project_id)
        project["gap_state"]["plan"] = gap_plan
        store._persist_project(project)
        manifests: list[dict] = []

        def fake_run_table_filler(manifest_path, progress_callback=None):
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            manifests.append(manifest)
            output_file = Path(manifest["outputFile"])
            doc = Document()
            doc.add_paragraph("性能保证附表")
            doc.save(output_file)
            return {
                "schema_version": "bid-tech-table-fill-v1",
                "outputFile": str(output_file),
                "unfilledFields": [],
                "evidenceRefs": [{"type": "material", "id": "RAW-0001"}],
                "fillReport": {"filledFieldCount": 2, "referenceMaterialCount": 1},
            }

        with patch(
            "app.services.gap_planning.run_table_filler_skill",
            side_effect=fake_run_table_filler,
        ):
            response = self.client.post(
                f"/api/projects/{project_id}/gaps/{gap_id}/ai-fill",
                json={
                    "fillTaskId": fill_task_id,
                    "referenceMaterialIds": ["RAW-0001"],
                    "parseFieldIds": ["APP-PERF", "FIELD-POWER"],
                    "operator": "测试用户",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        manifest = manifests[0]
        self.assertEqual(manifest["gapItem"]["id"], gap_id)
        self.assertEqual(manifest["appendixTask"]["id"], "APP-PERF")
        self.assertEqual(manifest["recommendedMaterials"][0]["id"], "RAW-0001")
        self.assertEqual(manifest["referenceMaterials"][0]["id"], "RAW-0001")
        self.assertEqual(manifest["parseFields"][0]["id"], "FIELD-POWER")
        self.assertEqual(manifest["blankSource"]["id"], "APP-PERF")
        artifact = response.json()["artifact"]
        self.assertEqual(artifact["fillReport"]["filledFieldCount"], 2)
        self.assertEqual(artifact["referenceMaterials"][0]["id"], "RAW-0001")

    def test_gap_upload_registers_real_project_artifact_for_s7(self) -> None:
        project_id = self._create_project_with_confirmed_directory_json()
        detection_response = self.client.post(f"/api/projects/{project_id}/gaps-detection/run")
        self.assertEqual(detection_response.status_code, 200)
        gap_plan = detection_response.json()["gapPlan"]
        gap_id = next(item for item in gap_plan["items"] if item["status"] == "needs_input")["id"]

        response = self.client.post(
            f"/api/projects/{project_id}/gaps/{gap_id}/upload",
            json={
                "bidType": "技术标",
                "files": [
                    {
                        "name": "客户补充性能保证.docx",
                        "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "data": "客户补充性能保证内容",
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["item"]["status"], "resolved")
        artifact = payload["artifact"]
        self.assertEqual(artifact["source"], "manual_upload")
        self.assertEqual(artifact["skill"], "")
        self.assertTrue(Path(artifact["path"]).exists())
        self.assertTrue(artifact["s7Ready"])
        gap_payload = self.client.get(f"/api/projects/{project_id}/gaps").json()
        updated_item = next(item for item in gap_payload["gapPlan"]["items"] if item["id"] == gap_id)
        self.assertEqual(updated_item["resolvedArtifacts"][0]["source"], "manual_upload")
        self.assertEqual(updated_item["status"], "resolved")

    def test_gap_upload_preserves_browser_docx_data_url_for_s7(self) -> None:
        project_id = self._create_project_with_confirmed_directory_json()
        detection_response = self.client.post(f"/api/projects/{project_id}/gaps-detection/run")
        self.assertEqual(detection_response.status_code, 200)
        gap_plan = detection_response.json()["gapPlan"]
        gap_id = next(item for item in gap_plan["items"] if item["status"] == "needs_input")["id"]

        upload_docx = Path(self.temp_dir.name) / "客户补充性能保证.docx"
        doc = Document()
        doc.add_paragraph("客户原始上传 Word 内容")
        doc.save(upload_docx)
        data_url = (
            "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,"
            + base64.b64encode(upload_docx.read_bytes()).decode("ascii")
        )

        response = self.client.post(
            f"/api/projects/{project_id}/gaps/{gap_id}/upload",
            json={
                "bidType": "技术标",
                "files": [
                    {
                        "name": "客户补充性能保证.docx",
                        "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "data": data_url,
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        artifact_path = Path(response.json()["artifact"]["path"])
        self.assertTrue(artifact_path.exists())
        uploaded_doc = Document(str(artifact_path))
        self.assertIn(
            "客户原始上传 Word 内容",
            "\n".join(paragraph.text for paragraph in uploaded_doc.paragraphs),
        )

    def test_gap_select_existing_material_registers_real_artifact_for_s7(self) -> None:
        project_id = self._create_project_with_confirmed_directory_json()
        detection_response = self.client.post(f"/api/projects/{project_id}/gaps-detection/run")
        self.assertEqual(detection_response.status_code, 200)
        gap_plan = detection_response.json()["gapPlan"]
        gap_id = next(item for item in gap_plan["items"] if item["status"] == "needs_input")["id"]

        prepared_docx = Path(self.temp_dir.name) / "素材库既有性能保证.docx"
        doc = Document()
        doc.add_paragraph("素材库既有 Word 内容")
        doc.save(prepared_docx)

        async def fake_prepare_existing_gap_material_files(project, selected_gap_id, data):
            self.assertEqual(selected_gap_id, gap_id)
            self.assertEqual(data["materials"][0]["id"], "RAW-0099")
            return [
                {
                    "materialId": "RAW-0099",
                    "materialName": "素材库既有性能保证",
                    "fileName": prepared_docx.name,
                    "path": str(prepared_docx),
                    "folderPath": "技术标/通用素材",
                    "materialTier": "standard",
                    "sourceKind": "cleaned",
                }
            ]

        with patch(
            "app.services.store.prepare_existing_gap_material_files",
            side_effect=fake_prepare_existing_gap_material_files,
        ):
            response = self.client.post(
                f"/api/projects/{project_id}/gaps/{gap_id}/select-material",
                json={
                    "materials": [
                        {
                            "id": "RAW-0099",
                            "name": "素材库既有性能保证",
                            "folderPath": "技术标/通用素材",
                            "materialTier": "standard",
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["item"]["status"], "resolved")
        artifact = payload["artifact"]
        self.assertEqual(artifact["source"], "material_library")
        self.assertEqual(artifact["materialId"], "RAW-0099")
        self.assertEqual(artifact["path"], str(prepared_docx))
        self.assertTrue(artifact["s7Ready"])
        self.assertIn("onlyoffice", artifact)
        updated_gap = self.client.get(f"/api/projects/{project_id}/gaps").json()["gapPlan"]
        updated_item = next(item for item in updated_gap["items"] if item["id"] == gap_id)
        self.assertEqual(updated_item["resolvedArtifacts"][0]["source"], "material_library")
        self.assertEqual(updated_item["resolvedArtifacts"][0]["path"], str(prepared_docx))

    def test_gap_detection_matches_material_from_s2_wiki_cards_when_toc_has_no_refs(self) -> None:
        project_id = self._create_project_with_confirmed_directory_json()
        project_dir = technical_workspace_dir(project_id)
        toc_json = project_dir / "s2_toc_workdir" / "投标文件-总目录.json"
        toc_data = json.loads(toc_json.read_text(encoding="utf-8"))
        for item in toc_data["items"]:
            item["material_refs"] = []
        toc_json.write_text(json.dumps(toc_data, ensure_ascii=False, indent=2), encoding="utf-8")
        wiki_cards = project_dir / "s2_toc_workdir" / "wiki" / "卡片"
        wiki_cards.mkdir(parents=True, exist_ok=True)
        (wiki_cards / "技术评分标准索引表.md").write_text(
            "---\n"
            "name: 技术评分标准索引表\n"
            "path: 技术标/通用素材/技术评分标准索引表.docx\n"
            "scope: 通用\n"
            "category: 技术标\n"
            "material_id: RAW-0001\n"
            "skeleton_section: \"1.1\"\n"
            "deprecated: false\n"
            "---\n",
            encoding="utf-8",
        )

        response = self.client.post(f"/api/projects/{project_id}/gaps-detection/run")

        self.assertEqual(response.status_code, 200)
        plan = response.json()["gapPlan"]
        matched = next(item for item in plan["items"] if item["number"] == "1.1")
        self.assertEqual(matched["status"], "matched")
        self.assertEqual(matched["matchedMaterials"][0]["id"], "RAW-0001")
        self.assertEqual(matched["matchedMaterials"][0]["source"], "wiki")

    def test_gap_detection_uses_one_chapter_master_for_wind_resource_chapter(self) -> None:
        project_id = self._create_project_with_confirmed_directory_json()
        project_dir = technical_workspace_dir(project_id)
        toc_json = project_dir / "s2_toc_workdir" / "投标文件-总目录.json"
        wind_candidates = [
            {
                "id": "RAW-0471",
                "name": "定制-项目风资源评估与机组选型排布及发电量计算.docx",
                "docx": "技术标/项目素材/MAT-HN-CHIFENG-001/技术标-专题方案要求/定制-项目风资源评估与机组选型排布及发电量计算.docx",
                "folderPath": "技术标/项目素材/MAT-HN-CHIFENG-001/技术标-专题方案要求",
                "materialTier": "project",
            },
            {
                "id": "RAW-0473",
                "name": "定制-风资源评估与机位排布方案.docx",
                "docx": "技术标/项目素材/MAT-HN-CHIFENG-001/技术标-风资源评估与机位排布方案/定制-风资源评估与机位排布方案.docx",
                "folderPath": "技术标/项目素材/MAT-HN-CHIFENG-001/技术标-风资源评估与机位排布方案",
                "materialTier": "project",
            },
            {
                "id": "RAW-0478",
                "name": "风资源评估报告.docx",
                "docx": "技术标/项目素材/MAT-HN-CHIFENG-001/风资源评估报告（解决方案部_风资源处：风资源流程传递）/风资源评估报告.docx",
                "folderPath": "技术标/项目素材/MAT-HN-CHIFENG-001/风资源评估报告（解决方案部_风资源处：风资源流程传递）",
                "materialTier": "project",
            },
        ]
        toc_json.write_text(
            json.dumps(
                {
                    "schema_version": "bid-toc-json-v1",
                    "items": [
                        {
                            "order": 1,
                            "number": "第3章",
                            "title": "风资源评估与机位排布方案",
                            "level": 1,
                            "annotation": "保留",
                            "source": "template",
                            "material_refs": wind_candidates,
                        },
                        *[
                            {
                                "order": index + 1,
                                "number": f"3.{index}",
                                "title": title,
                                "level": 2,
                                "annotation": "保留",
                                "source": "template",
                                "material_refs": wind_candidates if index in {4, 7} else [],
                            }
                            for index, title in enumerate(
                                [
                                    "总体方案概览",
                                    "项目概况",
                                    "风资源分析",
                                    "机组选型",
                                    "风机适应性分析",
                                    "方案及发电量结果",
                                    "不确定性分析",
                                ],
                                start=1,
                            )
                        ],
                        {
                            "order": 9,
                            "number": "附表E.1",
                            "title": "投标人风资源评估与机位排布方案",
                            "level": 1,
                            "annotation": "新增-附表空表",
                            "source": "tender_appendix",
                            "material_refs": [],
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        project = store._require(project_id)
        project["materialProjectId"] = "MAT-HN-CHIFENG-001"
        project["materialProjectCode"] = "MAT-HN-CHIFENG-001"
        project["materialProjectMode"] = "library"
        project["materialCustomerName"] = "华能集团"
        project["parse_result"]["structured"] = {
            "appendices": [
                {
                    "id": "APPX-0033",
                    "title": "附表E.1 投标人风资源评估与机位排布方案",
                    "sourceFile": "招标文件.docx",
                    "workspacePath": "/data/documents/PRJ-0003/parse/appendices/APPX-0033.docx",
                    "rowCount": 10,
                    "blankTable": True,
                }
            ]
        }
        store._persist_project(project)

        response = self.client.post(f"/api/projects/{project_id}/gaps-detection/run")

        self.assertEqual(response.status_code, 200, response.text)
        plan = response.json()["gapPlan"]
        self.assertFalse([item for item in plan["items"] if len(item.get("matchedMaterials") or []) > 1])
        parent = next(item for item in plan["items"] if item["number"] == "第3章")
        self.assertEqual(parent["decision"], "ready")
        self.assertEqual(parent["status"], "matched")
        self.assertEqual(parent["coverageRole"], "chapter_master")
        self.assertEqual(parent["matchedMaterials"][0]["id"], "RAW-0473")
        self.assertEqual(parent["matchedMaterials"][0]["usage"], "chapter_master")
        self.assertGreaterEqual(len(parent["candidateMaterials"]), 2)
        self.assertEqual(parent["appendixTasks"], [])
        for number in [f"3.{index}" for index in range(1, 8)]:
            child = next(item for item in plan["items"] if item["number"] == number)
            self.assertEqual(child["decision"], "ready")
            self.assertEqual(child["status"], "matched")
            self.assertEqual(child["coverageRole"], "covered_by_parent")
            self.assertEqual(child["coveredByParent"], parent["id"])
            self.assertEqual(child["matchedMaterials"], [])
            self.assertEqual(child["appendixTasks"], [])
            self.assertEqual(child["fillTasks"], [])
        appendix_item = next(item for item in plan["items"] if item["number"] == "附表E.1")
        self.assertEqual(appendix_item["decision"], "fill_required")
        self.assertEqual(appendix_item["status"], "needs_input")
        self.assertEqual(appendix_item["matchedMaterials"], [])
        self.assertEqual([task["id"] for task in appendix_item["appendixTasks"]], ["APPX-0033"])
        self.assertIn(
            "RAW-0473",
            [item["id"] for item in appendix_item["appendixTasks"][0]["recommendedMaterials"]],
        )
        self.assertEqual(appendix_item["appendixTasks"][0]["recommendedMaterials"][0]["id"], "RAW-0473")

    def test_gap_detection_manifest_contains_project_scoped_material_index(self) -> None:
        project_id = self._create_project_with_confirmed_directory_json()
        project = store._require(project_id)
        project["customerName"] = "华能集团"
        project["materialCustomerName"] = "华能集团"
        project["materialProjectId"] = "MAT-HN-CHIFENG-001"
        project["materialProjectCode"] = "MAT-HN-CHIFENG-001"
        project["materialProjectMode"] = "library"
        store._persist_project(project)
        manifests: list[dict] = []

        async def fake_raw_files(**kwargs):
            folder_path = str(kwargs.get("folder_path") or "")
            items = []
            if folder_path.endswith("MAT-HN-CHIFENG-001"):
                items.append(
                    {
                        "id": "RAW-0473",
                        "name": "定制-风资源评估与机位排布方案.docx",
                        "folderPath": "技术标/项目素材/MAT-HN-CHIFENG-001/技术标-风资源评估与机位排布方案",
                        "materialTier": "project",
                        "hasCleanedWord": True,
                        "cleanedFileName": "定制-风资源评估与机位排布方案.docx",
                    }
                )
            return {"items": items, "total": len(items), "page": 1, "pageSize": 1000}

        def fake_gap_planner(manifest_path):
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            manifests.append(manifest)
            output_file = Path(manifest["outputFile"])
            plan = {
                "schemaVersion": "bid-tech-gap-plan-v1",
                "projectId": project_id,
                "status": "ready",
                "summary": {
                    "totalTocItems": 0,
                    "matchedCount": 0,
                    "missingCount": 0,
                    "resolvedCount": 0,
                    "ignoredCount": 0,
                    "structuralCount": 0,
                    "fillableTaskCount": 0,
                    "blockingCount": 0,
                },
                "items": [],
            }
            output_file.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            return {"schema_version": "bid-tech-gap-plan-v1", "outputFile": str(output_file)}

        with patch("app.services.gap_planning.material_store.raw_files", side_effect=fake_raw_files), \
            patch("app.services.gap_planning.run_gap_planner_skill", side_effect=fake_gap_planner):
            response = self.client.post(f"/api/projects/{project_id}/gaps-detection/run")

        self.assertEqual(response.status_code, 200, response.text)
        manifest = manifests[0]
        self.assertEqual(
            manifest["materialScope"]["paths"],
            [
                "技术标/通用素材",
                "技术标/客户素材/华能集团",
                "技术标/项目素材/MAT-HN-CHIFENG-001",
            ],
        )
        self.assertEqual(manifest["materialIndex"][0]["id"], "RAW-0473")
        self.assertTrue(
            all(
                item["folderPath"].startswith(tuple(manifest["materialScope"]["paths"]))
                for item in manifest["materialIndex"]
            )
        )

    def test_gap_review_mock_flow_runs_from_s4_to_s6(self) -> None:
        project_id = self._create_project_with_confirmed_outline()

        detection_response = self.client.post(f"/api/projects/{project_id}/gaps-detection/run")
        self.assertEqual(detection_response.status_code, 200)
        detection_payload = detection_response.json()
        self.assertEqual(detection_payload["status"], "completed")
        self.assertGreater(len(detection_payload["items"]), 0)

        gaps_response = self.client.get(f"/api/projects/{project_id}/gaps")
        self.assertEqual(gaps_response.status_code, 200)
        gaps_payload = gaps_response.json()
        self.assertEqual(gaps_payload["status"], "ready")
        items = gaps_payload["items"]
        self.assertGreater(len(items), 0)

        for index, item in enumerate(items):
            submission_response = self.client.post(
                f"/api/projects/{project_id}/materials/submissions",
                json={
                    "missingId": item["id"],
                    "bidType": item.get("bidType") or "技术标",
                    "files": [
                        {
                            "name": f"{item['id']}.docx",
                            "size": 1024,
                            "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        }
                    ],
                },
            )
            self.assertEqual(submission_response.status_code, 200)

            if index % 2 == 0:
                update_response = self.client.put(
                    f"/api/projects/{project_id}/gaps/{item['id']}",
                    json={"action": "resolve", "source": {"name": f"{item['id']}.docx"}},
                )
            else:
                update_response = self.client.patch(
                    f"/api/projects/{project_id}/materials/missing/{item['id']}",
                    json={"status": "skipped", "reason": "MVP阶段先跳过"},
                )
            self.assertEqual(update_response.status_code, 200)

        submit_review_response = self.client.post(f"/api/projects/{project_id}/gaps/submit-review")
        self.assertEqual(submit_review_response.status_code, 200)

        review_items_response = self.client.get(f"/api/projects/{project_id}/review-items")
        self.assertEqual(review_items_response.status_code, 200)
        self.assertEqual(review_items_response.json()["status"], "ready")

        prepare_response = self.client.post(f"/api/projects/{project_id}/review-items/prepare")
        self.assertEqual(prepare_response.status_code, 200)

        review_document_response = self.client.get(f"/api/projects/{project_id}/review-items/document")
        self.assertEqual(review_document_response.status_code, 200)
        review_document = review_document_response.json()
        self.assertEqual(review_document["status"], "ready")
        self.assertIn("onlyoffice", review_document)
        self.assertIn("fileUrl", review_document["onlyoffice"])

        confirm_response = self.client.post(f"/api/projects/{project_id}/review-items/confirm")
        self.assertEqual(confirm_response.status_code, 200)
        self.assertEqual(confirm_response.json()["reviewStatus"], "confirmed")

    def test_submit_review_blocks_until_gap_plan_is_resolved(self) -> None:
        project_id = self._create_project_with_confirmed_outline()

        detection_response = self.client.post(f"/api/projects/{project_id}/gaps-detection/run")
        self.assertEqual(detection_response.status_code, 200)

        submit_review_response = self.client.post(f"/api/projects/{project_id}/gaps/submit-review")
        self.assertEqual(submit_review_response.status_code, 400)
        self.assertIn("缺口未解决", submit_review_response.json()["detail"])

        gaps_payload = self.client.get(f"/api/projects/{project_id}/gaps").json()
        for item in gaps_payload["items"]:
            update_response = self.client.patch(
                f"/api/projects/{project_id}/materials/missing/{item['id']}",
                json={"status": "skipped", "reason": "测试中人工确认忽略"},
            )
            self.assertEqual(update_response.status_code, 200)

        recheck_response = self.client.post(f"/api/projects/{project_id}/gaps/recheck")
        self.assertEqual(recheck_response.status_code, 200)
        self.assertEqual(recheck_response.json()["integrity"]["status"], "passed")

        submit_review_response = self.client.post(f"/api/projects/{project_id}/gaps/submit-review")
        self.assertEqual(submit_review_response.status_code, 200)
        submit_payload = submit_review_response.json()["payload"]
        self.assertTrue(submit_payload["submittedForReview"])
        self.assertGreater(len(submit_payload["items"]), 0)
        self.assertTrue(all(item["status"] == "skipped" for item in submit_payload["items"]))

        prepare_response = self.client.post(f"/api/projects/{project_id}/review-items/prepare")
        self.assertEqual(prepare_response.status_code, 200)
        review_items_response = self.client.get(f"/api/projects/{project_id}/review-items")
        self.assertEqual(review_items_response.status_code, 200)
        self.assertEqual(review_items_response.json()["summary"]["pendingCount"], 0)


if __name__ == "__main__":
    unittest.main()
