from __future__ import annotations

"""项目级实时表上传（POST /api/technical/projects/{pid}/gaps/facts/specs-upload）与 build_facts 门控测试。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import openpyxl
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import technical_gap_fact_table as fact_table_module
from app.services.store import store
from app.services.technical_fact_field_specs import fillable_specs
from app.services.technical_fact_spec_import import EXPECTED_HEADER

# 全局默认清单（148 条）里的独有字段，用于断言项目骨架不含全局清单字段
GLOBAL_ONLY_LABEL = "极端工况-Mx（kNm）"


def _build_xlsx(path: Path, rows: list[tuple[str, str]], header: list[str] | None = None) -> Path:
    """rows: (实际要填写的字段, 引用文件) 列表，引用文件决定 sourceKind。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header if header is not None else EXPECTED_HEADER)
    for index, (label, reference_file) in enumerate(rows, start=1):
        ws.append([index, "招标文件-技术规范书", "第一章 1.1", label, "", "", reference_file])
    wb.save(path)
    return path


class ProjectFactSpecsUploadTests(unittest.TestCase):
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

    def _create_project(self, *, recognition_completed: bool = False) -> str:
        response = self.client.post(
            "/api/technical/projects",
            json={"name": "实时表上传测试项目", "customerName": "测试业主"},
        )
        response.raise_for_status()
        project_id = response.json()["id"]
        if recognition_completed:
            project = store._require(project_id)
            project["identity"] = {"owner": "测试业主", "customerName": "测试业主"}
            project["gap_state"] = {
                "recognitionStatus": "completed",
                "recognizedAt": "2026-07-27T00:00:00",
                "submittedForReview": False,
                "reviewConfirmed": False,
                "reviewedAt": "",
                "items": [],
                "submissions": [],
                "plan": {},
                "planFile": "",
                "integrity": {},
                "projectFactTable": {},
            }
            store._persist_project(project)
        return project_id

    def _upload_specs(self, project_id: str, path: Path, filename: str = "实时表.xlsx"):
        with path.open("rb") as handle:
            return self.client.post(
                f"/api/technical/projects/{project_id}/gaps/facts/specs-upload",
                files={
                    "file": (
                        filename,
                        handle,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

    def test_upload_valid_xlsx_persists_fact_specs(self) -> None:
        project_id = self._create_project()
        xlsx_path = _build_xlsx(
            Path(self.temp_dir.name) / "实时表.xlsx",
            [("招标编号", "招标文件/招标公告"), ("总装机容量", "项目定制/工程量清单"), ("叶片产能", "/")],
        )

        response = self._upload_specs(project_id, xlsx_path)

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["specTotal"], 3)
        self.assertEqual(payload["fileName"], "实时表.xlsx")
        self.assertTrue(payload["uploadedAt"])

        project = store._require(project_id)
        fact_specs = project["gap_state"]["factSpecs"]
        self.assertEqual(fact_specs["fileName"], "实时表.xlsx")
        specs = fact_specs["specs"]
        self.assertEqual(len(specs), 3)
        self.assertEqual([spec["label"] for spec in specs], ["招标编号", "总装机容量", "叶片产能"])
        self.assertEqual(specs[0]["sourceKind"], "tender")
        self.assertEqual(specs[1]["sourceKind"], "material")

    def test_upload_rejects_wrong_header(self) -> None:
        project_id = self._create_project()
        xlsx_path = _build_xlsx(
            Path(self.temp_dir.name) / "坏表头.xlsx",
            [("招标编号", "招标文件/招标公告")],
            header=["A", "B", "C", "D", "E", "F", "G"],
        )

        response = self._upload_specs(project_id, xlsx_path)

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("表头", response.json()["detail"])
        self.assertNotIn("factSpecs", store._require(project_id).get("gap_state") or {})

    def test_upload_rejects_non_xlsx_filename(self) -> None:
        project_id = self._create_project()
        bad_path = Path(self.temp_dir.name) / "实时表.txt"
        bad_path.write_text("not an xlsx", encoding="utf-8")

        response = self._upload_specs(project_id, bad_path, filename="实时表.txt")

        self.assertEqual(response.status_code, 400, response.text)
        self.assertTrue(response.json()["detail"])
        self.assertNotIn("factSpecs", store._require(project_id).get("gap_state") or {})

    def test_build_facts_gate_blocks_until_specs_uploaded(self) -> None:
        project_id = self._create_project(recognition_completed=True)

        blocked = self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/build")
        self.assertEqual(blocked.status_code, 400, blocked.text)
        self.assertIn("请先上传", blocked.json()["detail"])

        xlsx_path = _build_xlsx(
            Path(self.temp_dir.name) / "实时表.xlsx",
            [("招标编号", "招标文件/招标公告"), ("总装机容量", "项目定制/工程量清单")],
        )
        self.assertEqual(self._upload_specs(project_id, xlsx_path).status_code, 200)

        build_response = self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/build")
        self.assertEqual(build_response.status_code, 200, build_response.text)
        payload = build_response.json()
        labels = [field["label"] for field in payload["fields"]]
        # 以清单为唯一字段骨架：字段行 == 上传清单的 2 条 spec，不含全局 148 条清单独有字段，
        # 匹配不到 spec 的启发式候选（项目名称/招标方等）不再单独成行
        self.assertIn("招标编号", labels)
        self.assertIn("总装机容量", labels)
        self.assertEqual(len(payload["fields"]), 2)
        self.assertTrue(all(field.get("specSeq") for field in payload["fields"]))
        self.assertTrue(any(spec["label"] == GLOBAL_ONLY_LABEL for spec in fillable_specs()))
        self.assertNotIn(GLOBAL_ONLY_LABEL, labels)
        self.assertEqual(payload["summary"]["specTotal"], 2)

    def test_facts_metadata_reflects_specs_upload(self) -> None:
        project_id = self._create_project()

        before = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts")
        self.assertEqual(before.status_code, 200, before.text)
        self.assertFalse(before.json()["specsImported"])
        self.assertEqual(before.json()["specTotal"], 0)

        xlsx_path = _build_xlsx(
            Path(self.temp_dir.name) / "实时表.xlsx",
            [("招标编号", "招标文件/招标公告"), ("总装机容量", "项目定制/工程量清单")],
        )
        self.assertEqual(self._upload_specs(project_id, xlsx_path).status_code, 200)

        after = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts")
        self.assertEqual(after.status_code, 200, after.text)
        self.assertTrue(after.json()["specsImported"])
        self.assertEqual(after.json()["specsFileName"], "实时表.xlsx")
        # specTotal 始终表示上传规则条数，构建前后口径不变。
        self.assertEqual(after.json()["specTotal"], 2)

    def test_draft_save_preserves_rule_reference_and_spec_total(self) -> None:
        project_id = self._create_project()
        xlsx_path = _build_xlsx(
            Path(self.temp_dir.name) / "事实表.xlsx",
            [("招标编号", "招标文件/招标公告"), ("总装机容量", "项目定制/工程量清单")],
        )
        self.assertEqual(self._upload_specs(project_id, xlsx_path).status_code, 200)
        built = self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/build")
        self.assertEqual(built.status_code, 200, built.text)

        saved = self.client.put(
            f"/api/technical/projects/{project_id}/gaps/facts",
            json={"fields": built.json()["fields"], "confirm": False, "operator": "测试用户"},
        )

        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["factSpecsRef"], built.json()["factSpecsRef"])
        self.assertEqual(saved.json()["summary"]["specTotal"], 2)


    def test_material_sources_roundtrip(self) -> None:
        project_id = self._create_project()

        before = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts")
        self.assertEqual(before.status_code, 200, before.text)
        self.assertEqual(before.json()["materialPaths"], [])

        response = self.client.put(
            f"/api/technical/projects/{project_id}/gaps/facts/material-sources",
            json={"paths": ["技术标/项目定制/其他项目/", " 技术标/项目定制/其他项目 ", "技术标/客户定制/某业主"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        # 去空白、去尾斜杠、去重
        self.assertEqual(
            response.json()["paths"], ["技术标/项目定制/其他项目", "技术标/客户定制/某业主"]
        )

        project = store._require(project_id)
        self.assertEqual(
            project["gap_state"]["factMaterialPaths"],
            ["技术标/项目定制/其他项目", "技术标/客户定制/某业主"],
        )

        after = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts")
        self.assertEqual(
            after.json()["materialPaths"], ["技术标/项目定制/其他项目", "技术标/客户定制/某业主"]
        )

    def test_material_sources_rejects_non_list(self) -> None:
        project_id = self._create_project()

        response = self.client.put(
            f"/api/technical/projects/{project_id}/gaps/facts/material-sources",
            json={"paths": "技术标/项目定制/其他项目"},
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertNotIn("factMaterialPaths", store._require(project_id).get("gap_state") or {})

    def test_material_sources_prefix_tolerance(self) -> None:
        """用户省略标类前缀（项目定制/xxx）时自动补全为素材库完整路径。"""
        project_id = self._create_project()

        response = self.client.put(
            f"/api/technical/projects/{project_id}/gaps/facts/material-sources",
            json={"paths": ["项目定制/其他项目"]},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["paths"], ["技术标/项目定制/其他项目"])


class ProjectFactMaterialIndexScopeTests(unittest.TestCase):
    """素材回退扫描只查本项目「项目定制」目录，不扫标准/客户定制目录。"""

    def test_fallback_scan_only_queries_project_tier_scope(self) -> None:
        scopes = [
            {"materialTier": "standard", "path": "技术标/标准素材"},
            {"materialTier": "customer", "path": "技术标/客户定制/测试业主"},
            {"materialTier": "project", "path": "技术标/项目定制/实时表上传测试项目"},
        ]
        calls: list[dict] = []

        def fake_material_files(**kwargs):
            calls.append(kwargs)
            return {
                "items": [
                    {
                        "id": "RAW-P1",
                        "name": "塔架与基础工程量.xlsx",
                        "folderPath": "技术标/项目定制/实时表上传测试项目",
                        "materialTier": "project",
                    }
                ]
            }

        with (
            patch.object(
                fact_table_module,
                "build_project_material_scope",
                lambda project: {"readableScopes": scopes},
            ),
            patch.object(
                fact_table_module, "run_async_material_files", side_effect=fake_material_files
            ),
        ):
            # gap_state 无 plan.materialIndex，走回退扫描
            materials = fact_table_module.project_fact_material_index(
                {"id": "P-SCOPE", "name": "实时表上传测试项目"}, {"plan": {}}
            )

        self.assertEqual(
            [call["folder_path"] for call in calls], ["技术标/项目定制/实时表上传测试项目"]
        )
        self.assertTrue(all(call["material_tier"] == "project" for call in calls))
        self.assertEqual([material["id"] for material in materials], ["RAW-P1"])

    def test_fallback_scan_includes_custom_material_paths(self) -> None:
        """用户自定义的参考资料目录并入回退扫描；显式配置的目录不按 tier 过滤（空串）。"""
        scopes = [
            {"materialTier": "standard", "path": "技术标/标准素材"},
            {"materialTier": "project", "path": "技术标/项目定制/实时表上传测试项目"},
        ]
        calls: list[dict] = []

        def fake_material_files(**kwargs):
            calls.append(kwargs)
            return {"items": []}

        with (
            patch.object(
                fact_table_module,
                "build_project_material_scope",
                lambda project: {"readableScopes": scopes},
            ),
            patch.object(
                fact_table_module, "run_async_material_files", side_effect=fake_material_files
            ),
        ):
            fact_table_module.project_fact_material_index(
                {"id": "P-SCOPE", "name": "实时表上传测试项目"},
                # 兼容早期存入的缺标类前缀路径：扫描侧同样补全
                {"plan": {}, "factMaterialPaths": ["项目定制/其他项目"]},
            )

        self.assertEqual(
            [call["folder_path"] for call in calls],
            ["技术标/项目定制/实时表上传测试项目", "技术标/项目定制/其他项目"],
        )
        # 项目定制默认目录仍按 project 层过滤；自定义参考目录不过滤 tier
        self.assertEqual([call["material_tier"] for call in calls], ["project", ""])

    def test_custom_material_paths_include_standard_tier_materials(self) -> None:
        """自定义参考目录下 tier=standard 的真实数据素材也能进索引（回归：整目录被 tier 过滤误伤）。"""
        scopes = [{"materialTier": "project", "path": "技术标/项目定制/实时表上传测试项目"}]

        def fake_material_files(**kwargs):
            if kwargs["folder_path"] == "技术标/项目定制/北区参考项目":
                return {
                    "items": [
                        {
                            "id": "RAW-N1",
                            "name": "风资源评估报告.docx",
                            "folderPath": "技术标/项目定制/北区参考项目",
                            "materialTier": "standard",
                        },
                        {
                            "id": "RAW-N2",
                            "name": "基础弯矩表.xlsx",
                            "folderPath": "技术标/项目定制/北区参考项目",
                            "materialTier": "standard",
                        },
                    ]
                }
            return {"items": []}

        with (
            patch.object(
                fact_table_module,
                "build_project_material_scope",
                lambda project: {"readableScopes": scopes},
            ),
            patch.object(
                fact_table_module, "run_async_material_files", side_effect=fake_material_files
            ),
        ):
            materials = fact_table_module.project_fact_material_index(
                {"id": "P-SCOPE", "name": "实时表上传测试项目"},
                {"plan": {}, "factMaterialPaths": ["技术标/项目定制/北区参考项目"]},
            )

        self.assertEqual([material["id"] for material in materials], ["RAW-N1", "RAW-N2"])
        self.assertTrue(all(material["materialTier"] == "standard" for material in materials))

    def test_custom_material_paths_union_with_plan_index_and_dedupe(self) -> None:
        """已有 plan.materialIndex 时仍扫描自定义目录，并按素材 ID 合并去重。"""
        calls: list[dict] = []

        def fake_material_files(**kwargs):
            calls.append(kwargs)
            return {
                "items": [
                    {
                        "id": "RAW-PLAN",
                        "name": "计划内风资源报告.docx",
                        "folderPath": "技术标/项目定制/当前项目",
                        "materialTier": "project",
                    },
                    {
                        "id": "RAW-CUSTOM",
                        "name": "参考项目风资源报告.docx",
                        "folderPath": "技术标/项目定制/参考项目",
                        "materialTier": "standard",
                    },
                ]
            }

        with patch.object(
            fact_table_module, "run_async_material_files", side_effect=fake_material_files
        ):
            materials = fact_table_module.project_fact_material_index(
                {"id": "P-SCOPE", "name": "当前项目"},
                {
                    "plan": {
                        "materialIndex": [
                            {
                                "id": "RAW-PLAN",
                                "name": "计划内风资源报告.docx",
                                "folderPath": "技术标/项目定制/当前项目",
                                "materialTier": "project",
                            }
                        ]
                    },
                    "factMaterialPaths": ["技术标/项目定制/参考项目"],
                },
            )

        self.assertEqual([call["folder_path"] for call in calls], ["技术标/项目定制/参考项目"])
        self.assertEqual([material["id"] for material in materials], ["RAW-PLAN", "RAW-CUSTOM"])

    def test_fill_templates_excluded_from_index(self) -> None:
        """「待填写」前缀的附表模板不进索引（它们是要填的目标表格，不是取数素材）。"""
        scopes = [{"materialTier": "project", "path": "技术标/项目定制/实时表上传测试项目"}]

        def fake_material_files(**kwargs):
            return {
                "items": [
                    {
                        "id": "RAW-TPL",
                        "name": "待填写-附表1 塔架与基础工程量.docx",
                        "folderPath": "技术标/项目定制/实时表上传测试项目",
                        "materialTier": "project",
                    },
                    {
                        "id": "RAW-DATA",
                        "name": "基础弯矩表.xlsx",
                        "folderPath": "技术标/项目定制/实时表上传测试项目",
                        "materialTier": "project",
                    },
                ]
            }

        with (
            patch.object(
                fact_table_module,
                "build_project_material_scope",
                lambda project: {"readableScopes": scopes},
            ),
            patch.object(
                fact_table_module, "run_async_material_files", side_effect=fake_material_files
            ),
        ):
            materials = fact_table_module.project_fact_material_index(
                {"id": "P-SCOPE", "name": "实时表上传测试项目"}, {"plan": {}}
            )

        self.assertEqual([material["id"] for material in materials], ["RAW-DATA"])


if __name__ == "__main__":
    unittest.main()
