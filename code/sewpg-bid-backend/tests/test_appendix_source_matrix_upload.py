from __future__ import annotations

"""项目级附表来源矩阵上传（POST /api/technical/projects/{pid}/appendix-source-matrix）测试。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import openpyxl
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services.store import store
from app.services.technical_appendix_source_matrix import (
    appendix_rule_code_score,
    apply_appendix_source_matrix_to_plan,
    load_appendix_source_matrix_for_project,
)

MATRIX_HEADER = ["客户", "表格", "项目定制", "标准文件", "其他"]


def _build_matrix_xlsx(path: Path, rows: list[list[str]], header: list[str] | None = None) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header if header is not None else MATRIX_HEADER)
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


class AppendixSourceMatrixUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.ensure_dirs()

        store.reset_for_tests()
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def _create_project(self) -> str:
        response = self.client.post(
            "/api/technical/projects",
            json={"name": "附表规则上传测试项目", "customerName": "华能"},
        )
        response.raise_for_status()
        return response.json()["id"]

    def _upload_matrix(self, project_id: str, path: Path, filename: str = "填写文件来源.xlsx"):
        with path.open("rb") as handle:
            return self.client.post(
                f"/api/technical/projects/{project_id}/appendix-source-matrix",
                files={
                    "file": (
                        filename,
                        handle,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

    def test_upload_valid_matrix_binds_project(self) -> None:
        project_id = self._create_project()
        xlsx_path = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "填写文件来源.xlsx",
            [
                ["华能", "附表A.1 投标机型总方案信息表", "塔架与基础工程量&风资源评估报告", "机型参数表", ""],
                ["华能", "附表C.1 总体技术参数与规格", "", "机型参数表", ""],
                ["华能", "附表B.5 培训内容和计划表", "", "", "响应招标文件填写"],
            ],
        )

        response = self._upload_matrix(project_id, xlsx_path)

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["rowCount"], 3)
        self.assertEqual(payload["fileName"], "填写文件来源.xlsx")
        self.assertTrue(payload["uploadedAt"])

        project = store._require(project_id)
        binding = project["technicalAppendixSourceMatrix"]
        self.assertEqual(binding["fileName"], "填写文件来源.xlsx")
        self.assertEqual(binding["rowCount"], 3)
        bound_path = Path(binding["path"])
        self.assertTrue(bound_path.exists())
        self.assertEqual(bound_path, settings.documents_dir / project_id / "technical-workspace" / "appendix-source-matrix.xlsx")

        matrix = load_appendix_source_matrix_for_project(project)
        self.assertEqual(str(matrix["path"]), str(bound_path))
        self.assertEqual(len(matrix["rows"]), 3)
        self.assertEqual(matrix["rows"][0]["projectSources"], ["塔架与基础工程量", "风资源评估报告"])

    def test_facts_payload_carries_matrix_meta(self) -> None:
        project_id = self._create_project()
        before = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts")
        self.assertEqual(before.status_code, 200, before.text)
        self.assertEqual(before.json()["appendixSourceMatrix"], {})

        xlsx_path = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "填写文件来源.xlsx",
            [["华能", "附表C.1 总体技术参数与规格", "", "机型参数表", ""]],
        )
        self._upload_matrix(project_id, xlsx_path).raise_for_status()

        after = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts")
        self.assertEqual(after.status_code, 200, after.text)
        meta = after.json()["appendixSourceMatrix"]
        self.assertEqual(meta["fileName"], "填写文件来源.xlsx")
        self.assertEqual(meta["rowCount"], 1)
        self.assertTrue(meta["path"])

    def test_upload_rejects_non_xlsx(self) -> None:
        project_id = self._create_project()
        response = self.client.post(
            f"/api/technical/projects/{project_id}/appendix-source-matrix",
            files={"file": ("规则.txt", b"not an xlsx", "text/plain")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(store._require(project_id)["technicalAppendixSourceMatrix"])

    def test_upload_rejects_matrix_without_valid_rows(self) -> None:
        project_id = self._create_project()
        xlsx_path = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "坏表头.xlsx",
            [["华能", "附表C.1 总体技术参数与规格", "", "机型参数表", ""]],
            header=["A", "B", "C", "D", "E"],
        )

        response = self._upload_matrix(project_id, xlsx_path)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(store._require(project_id)["technicalAppendixSourceMatrix"])

    def test_reupload_overwrites_binding(self) -> None:
        project_id = self._create_project()
        first = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "第一版.xlsx",
            [["华能", "附表C.1 总体技术参数与规格", "", "机型参数表", ""]],
        )
        self._upload_matrix(project_id, first, filename="第一版.xlsx").raise_for_status()

        second = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "第二版.xlsx",
            [
                ["华能", "附表C.1 总体技术参数与规格", "", "机型参数表", ""],
                ["华能", "附表D.1 标准及风电场空气密度功率曲线", "功率曲线", "", ""],
            ],
        )
        response = self._upload_matrix(project_id, second, filename="第二版.xlsx")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["rowCount"], 2)
        binding = store._require(project_id)["technicalAppendixSourceMatrix"]
        self.assertEqual(binding["fileName"], "第二版.xlsx")
        self.assertEqual(binding["rowCount"], 2)
        matrix = load_appendix_source_matrix_for_project(store._require(project_id))
        self.assertEqual(len(matrix["rows"]), 2)

    def _seed_completed_plan(self, project_id: str) -> None:
        project = store._require(project_id)
        project["gap_state"] = {
            "recognitionStatus": "completed",
            "recognizedAt": "2026-08-05T00:00:00",
            "submittedForReview": False,
            "reviewConfirmed": False,
            "reviewedAt": "",
            "items": [],
            "submissions": [],
            "plan": {
                "items": [
                    {
                        "id": "toc-1",
                        "number": "附表C.2",
                        "title": "风轮系统技术参数",
                        "appendixTasks": [
                            {"id": "APPX-0001", "title": "附表C.2 风轮系统技术参数", "recommendedMaterials": []}
                        ],
                        "fillTasks": [],
                    },
                    {
                        "id": "toc-2",
                        "number": "附表X.9",
                        "title": "规则外附表",
                        "appendixTasks": [
                            {"id": "APPX-0002", "title": "附表X.9 规则外附表", "recommendedMaterials": [{"id": "keep-me"}]}
                        ],
                        "fillTasks": [],
                    },
                ]
            },
            "planFile": "",
            "integrity": {},
            "projectFactTable": {},
        }
        store._persist_project(project)

    def test_upload_applies_matrix_to_existing_plan(self) -> None:
        project_id = self._create_project()
        self._seed_completed_plan(project_id)
        materials = [
            {
                "id": "RAW-0001",
                "name": "W10 机型参数表.xlsx",
                "folderPath": "技术标/标准文件/机型参数表",
                "materialTier": "standard",
            },
            {
                "id": "RAW-0002",
                "name": "无关素材.docx",
                "folderPath": "技术标/项目定制/华能/其他",
                "materialTier": "project",
            },
        ]
        xlsx_path = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "填写文件来源.xlsx",
            [["华能", "附表C.2 风轮系统技术参数", "", "机型参数表", ""]],
        )

        with patch(
            "app.services.technical_gap_planner._allowed_technical_material_index",
            return_value=materials,
        ):
            response = self._upload_matrix(project_id, xlsx_path)

        self.assertEqual(response.status_code, 200, response.text)
        applied = response.json()["applied"]
        self.assertEqual(applied["routedItems"], 1)
        self.assertEqual(applied["matchedTasks"], 1)

        plan = store._require(project_id)["gap_state"]["plan"]
        routed_item, untouched_item = plan["items"]
        task = routed_item["appendixTasks"][0]
        self.assertEqual(task["sourceRouting"]["source"], "appendix_source_matrix")
        self.assertEqual(task["sourceRouting"]["status"], "matched")
        self.assertEqual(task["sourceRouting"]["standardSources"], ["机型参数表"])
        recommended_ids = [m["id"] for m in task["recommendedMaterials"]]
        self.assertEqual(recommended_ids, ["RAW-0001"])
        self.assertEqual(task["recommendedMaterials"][0]["usage"], "table_source")
        self.assertEqual(routed_item["sourceRouting"]["source"], "appendix_source_matrix")
        self.assertEqual([m["id"] for m in routed_item["sourceRoutedMaterials"]], ["RAW-0001"])
        # 规则未命中的任务保持原样
        self.assertNotIn("sourceRouting", untouched_item["appendixTasks"][0])
        self.assertEqual(untouched_item["appendixTasks"][0]["recommendedMaterials"], [{"id": "keep-me"}])

    def test_reupload_replaces_old_matrix_routing_in_existing_plan(self) -> None:
        project_id = self._create_project()
        self._seed_completed_plan(project_id)
        materials = [
            {
                "id": "RAW-0001",
                "name": "W10 机型参数表.xlsx",
                "folderPath": "技术标/标准文件/机型参数表",
                "materialTier": "standard",
            },
            {
                "id": "RAW-0002",
                "name": "规则外附表来源.docx",
                "folderPath": "技术标/项目定制/华能/规则外附表来源",
                "materialTier": "project",
            },
        ]
        first = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "第一版.xlsx",
            [["华能", "附表C.2 风轮系统技术参数", "", "机型参数表", ""]],
        )
        second = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "第二版.xlsx",
            [["华能", "附表X.9 规则外附表", "规则外附表来源", "", ""]],
        )

        with patch(
            "app.services.technical_gap_planner._allowed_technical_material_index",
            return_value=materials,
        ):
            self._upload_matrix(project_id, first, filename="第一版.xlsx").raise_for_status()
            response = self._upload_matrix(project_id, second, filename="第二版.xlsx")

        self.assertEqual(response.status_code, 200, response.text)
        plan = store._require(project_id)["gap_state"]["plan"]
        removed_item, new_item = plan["items"]
        removed_task = removed_item["appendixTasks"][0]
        self.assertNotIn("sourceRouting", removed_task)
        self.assertEqual(removed_task["recommendedMaterials"], [])
        self.assertNotIn("sourceRouting", removed_item)
        self.assertNotIn("sourceRoutedMaterials", removed_item)

        new_task = new_item["appendixTasks"][0]
        self.assertEqual(new_task["sourceRouting"]["ruleId"], "Sheet!R2")
        self.assertEqual([item["id"] for item in new_task["recommendedMaterials"]], ["RAW-0002"])
        self.assertEqual([item["id"] for item in new_item["sourceRoutedMaterials"]], ["RAW-0002"])

    def test_upload_without_plan_returns_empty_applied(self) -> None:
        project_id = self._create_project()
        xlsx_path = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "填写文件来源.xlsx",
            [["华能", "附表C.2 风轮系统技术参数", "", "机型参数表", ""]],
        )
        response = self._upload_matrix(project_id, xlsx_path)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["applied"], {})


class ApplyMatrixToPlanTests(unittest.TestCase):
    """apply_appendix_source_matrix_to_plan 的状态分支（manual/tender/missing）。"""

    @staticmethod
    def _plan() -> dict:
        return {
            "items": [
                {
                    "id": "toc-1",
                    "appendixTasks": [
                        {"id": "A1", "title": "附表D.8 MTBF与MTTR"},
                        {"id": "A2", "title": "附表B.5 培训内容和计划表"},
                        {"id": "A3", "title": "附表D.1 标准及风电场空气密度功率曲线"},
                    ],
                }
            ]
        }

    @staticmethod
    def _matrix() -> dict:
        return {
            "rows": [
                {"id": "Sheet1!R2", "customer": "华能", "tableTitle": "附表D.8 MTBF与MTTR",
                 "projectSources": [], "standardSources": [], "otherSources": ["项目定制收集"]},
                {"id": "Sheet1!R3", "customer": "华能", "tableTitle": "附表B.5 培训内容和计划表",
                 "projectSources": [], "standardSources": [], "otherSources": ["响应招标文件填写"]},
                {"id": "Sheet1!R4", "customer": "华能", "tableTitle": "附表D.1 标准及风电场空气密度功率曲线",
                 "projectSources": ["功率曲线"], "standardSources": [], "otherSources": []},
            ]
        }

    def test_status_branches(self) -> None:
        plan = self._plan()
        stats = apply_appendix_source_matrix_to_plan(
            plan, self._matrix(), customer_name="华能", materials=[]
        )
        tasks = plan["items"][0]["appendixTasks"]
        self.assertEqual(tasks[0]["sourceRouting"]["status"], "manual_required")
        self.assertTrue(tasks[0]["sourceRouting"]["manualRequired"])
        self.assertEqual(tasks[1]["sourceRouting"]["status"], "tender_parse_fields")
        self.assertTrue(tasks[1]["sourceRouting"]["useTenderParseFields"])
        self.assertEqual(tasks[2]["sourceRouting"]["status"], "missing_source")
        self.assertEqual(stats["routedItems"], 1)
        self.assertEqual(stats["manualRequired"], 1)
        self.assertEqual(stats["tenderFields"], 1)
        self.assertEqual(stats["missingSource"], 1)
        self.assertEqual(stats["matchedTasks"], 0)

    def test_empty_matrix_or_plan_is_noop(self) -> None:
        plan = self._plan()
        self.assertEqual(
            apply_appendix_source_matrix_to_plan(plan, {"rows": []}, customer_name="华能", materials=[]),
            {"routedItems": 0, "matchedTasks": 0, "manualRequired": 0, "tenderFields": 0, "missingSource": 0},
        )
        self.assertNotIn("sourceRouting", plan["items"][0]["appendixTasks"][0])

    def test_non_matrix_routing_is_not_overwritten(self) -> None:
        plan = {
            "items": [
                {
                    "id": "toc-client",
                    "appendixTasks": [
                        {
                            "id": "A1",
                            "title": "附表C.2 风轮系统技术参数",
                            "sourceRouting": {"source": "client_appendix_input", "status": "client_provided"},
                            "recommendedMaterials": [{"id": "RAW-CLIENT"}],
                        }
                    ],
                }
            ]
        }
        matrix = {
            "rows": [
                {
                    "id": "Sheet1!R2",
                    "customer": "华能",
                    "tableTitle": "附表C.2 风轮系统技术参数",
                    "projectSources": [],
                    "standardSources": ["机型参数表"],
                    "otherSources": [],
                }
            ]
        }

        stats = apply_appendix_source_matrix_to_plan(
            plan,
            matrix,
            customer_name="华能",
            materials=[{"id": "RAW-PARAM", "name": "机型参数表.xlsx", "materialTier": "standard"}],
        )

        task = plan["items"][0]["appendixTasks"][0]
        self.assertEqual(stats["routedItems"], 0)
        self.assertEqual(task["sourceRouting"]["source"], "client_appendix_input")
        self.assertEqual(task["recommendedMaterials"], [{"id": "RAW-CLIENT"}])


class AppendixRuleCodeScoreTests(unittest.TestCase):
    """父级编号规则覆盖子编号附表（F.2 规则命中 F.2.1）。"""

    def test_parent_rule_covers_sub_numbered_table(self) -> None:
        self.assertEqual(
            appendix_rule_code_score("附表F.2.1 投标机组设计认证", "附表F.2 投标机型整机认证"),
            0.93,
        )
        self.assertEqual(
            appendix_rule_code_score("附表G.3.2 塔筒极限强度设计安全余量", "附表G.3 钢塔筒招标项目场址设计安全性"),
            0.93,
        )

    def test_exact_and_range_scores_unchanged(self) -> None:
        self.assertEqual(
            appendix_rule_code_score("附表C.1 总体技术参数与规格", "附表C.1 总体技术参数与规格"),
            0.96,
        )
        self.assertEqual(appendix_rule_code_score("附表D.3 功率曲线", "附表D.1-D.6"), 0.94)

    def test_sub_code_coverage_boundaries(self) -> None:
        # 前缀不同不覆盖
        self.assertEqual(appendix_rule_code_score("附表G.2.1 场址载荷", "附表F.2 整机认证"), 0.0)
        # 反向（子级规则覆盖父级附表）不成立
        self.assertEqual(appendix_rule_code_score("附表F.2 整机认证", "附表F.2.1 设计认证"), 0.0)
        # 兄弟编号不覆盖
        self.assertEqual(appendix_rule_code_score("附表F.3.1 大部件认证", "附表F.2 整机认证"), 0.0)

    def test_apply_routes_sub_numbered_task_by_parent_rule(self) -> None:
        plan = {
            "items": [
                {
                    "id": "toc-1",
                    "appendixTasks": [{"id": "A1", "title": "附表F.2.1 投标机组设计认证"}],
                }
            ]
        }
        matrix = {
            "rows": [
                {
                    "id": "Sheet1!R33",
                    "customer": "华能",
                    "tableTitle": "附表F.2 投标机型整机认证",
                    "projectSources": [],
                    "standardSources": ["认证证书"],
                    "otherSources": [],
                }
            ]
        }
        materials = [
            {
                "id": "RAW-CERT",
                "name": "EW10.0-220上置型式认证证书.pdf",
                "folderPath": "技术标/标准文件/EW10.0-220上置/认证证书",
                "materialTier": "standard",
            }
        ]
        stats = apply_appendix_source_matrix_to_plan(plan, matrix, customer_name="华能", materials=materials)
        task = plan["items"][0]["appendixTasks"][0]
        self.assertEqual(task["sourceRouting"]["ruleId"], "Sheet1!R33")
        self.assertEqual(task["recommendedMaterials"][0]["id"], "RAW-CERT")
        self.assertEqual(stats["matchedTasks"], 1)


if __name__ == "__main__":
    unittest.main()
