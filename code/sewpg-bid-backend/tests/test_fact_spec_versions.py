from __future__ import annotations

"""填表规则版本化与项目绑定（R06-B04-02）测试。

覆盖验收标准：
- 项目 A/B 交错上传与运行互不污染（各自 build 始终用自己的规则版本）；
- B 上传新版本不改变 A 的绑定；
- 每次上传生成不可变版本文件（ruleId/版本号/上传人/时间/sha256），重启后可从数据卷读回；
- 无绑定项目回落系统默认规则；
- AI 维护（curator）manifest 按项目绑定版本关联 spec。
"""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import openpyxl
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import technical_fact_curator as curator
from app.services.store import store
from app.services.technical_fact_field_specs import load_specs
from app.services.technical_fact_spec_import import EXPECTED_HEADER
from app.services.technical_fact_spec_versions import (
    FACT_SPECS_SOURCE_DEFAULT,
    FACT_SPECS_SOURCE_PROJECT,
    load_fact_spec_version,
    resolve_project_specs,
)


def _build_xlsx(path: Path, labels: list[str]) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(EXPECTED_HEADER)
    for index, label in enumerate(labels, start=1):
        ws.append([index, "招标文件-技术规范书", "第一章 1.1", label, "", "", "招标文件/技术规范书"])
    wb.save(path)
    return path


class ProjectFactSpecVersionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        self._orig_dirs = (
            settings.uploads_dir,
            settings.documents_dir,
            settings.parsed_dir,
            settings.fact_specs_versions_dir,
        )
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.fact_specs_versions_dir = base / "fact_spec_versions"
        settings.ensure_dirs()

        store.reset_for_tests()
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")

    def tearDown(self) -> None:
        self.client.close()
        (
            settings.uploads_dir,
            settings.documents_dir,
            settings.parsed_dir,
            settings.fact_specs_versions_dir,
        ) = self._orig_dirs
        self.temp_dir.cleanup()

    def _create_project(self, name: str) -> str:
        response = self.client.post(
            "/api/technical/projects",
            json={"name": name, "customerName": "测试业主"},
        )
        response.raise_for_status()
        project_id = response.json()["id"]
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

    def _build_facts(self, project_id: str) -> dict:
        response = self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/build")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_interleaved_uploads_and_builds_stay_isolated(self) -> None:
        project_a = self._create_project("项目A")
        project_b = self._create_project("项目B")
        base = Path(self.temp_dir.name)

        rules_a = _build_xlsx(base / "规则A.xlsx", ["招标编号", "总装机容量"])
        rules_b1 = _build_xlsx(base / "规则B1.xlsx", ["叶片产能"])
        rules_b2 = _build_xlsx(base / "规则B2.xlsx", ["叶片产能", "塔架重量"])

        upload_a = self._upload_specs(project_a, rules_a, "规则A.xlsx")
        self.assertEqual(upload_a.status_code, 200, upload_a.text)
        upload_b1 = self._upload_specs(project_b, rules_b1, "规则B1.xlsx")
        self.assertEqual(upload_b1.status_code, 200, upload_b1.text)
        rule_a = upload_a.json()["ruleId"]
        rule_b = upload_b1.json()["ruleId"]
        self.assertNotEqual(rule_a, rule_b)
        self.assertEqual(upload_a.json()["version"], 1)
        self.assertEqual(upload_b1.json()["version"], 1)

        # A 构建事实表：骨架只含规则 A 字段，且固化规则版本快照
        table_a = self._build_facts(project_a)
        labels_a = [field["label"] for field in table_a["fields"]]
        self.assertIn("招标编号", labels_a)
        self.assertIn("总装机容量", labels_a)
        self.assertNotIn("叶片产能", labels_a)
        self.assertEqual(table_a["factSpecsRef"]["ruleId"], rule_a)
        self.assertEqual(table_a["factSpecsRef"]["version"], 1)
        self.assertEqual(table_a["factSpecsRef"]["source"], FACT_SPECS_SOURCE_PROJECT)

        # B 上传新版本（v2），交错运行：A 再构建仍用规则 A v1
        upload_b2 = self._upload_specs(project_b, rules_b2, "规则B2.xlsx")
        self.assertEqual(upload_b2.status_code, 200, upload_b2.text)
        self.assertEqual(upload_b2.json()["version"], 2)
        self.assertNotEqual(upload_b2.json()["ruleId"], rule_b)

        table_a2 = self._build_facts(project_a)
        labels_a2 = [field["label"] for field in table_a2["fields"]]
        self.assertIn("招标编号", labels_a2)
        self.assertNotIn("叶片产能", labels_a2)
        self.assertNotIn("塔架重量", labels_a2)
        self.assertEqual(table_a2["factSpecsRef"]["ruleId"], rule_a)
        self.assertEqual(table_a2["factSpecsRef"]["version"], 1)

        # B 构建用自己的 v2
        table_b = self._build_facts(project_b)
        labels_b = [field["label"] for field in table_b["fields"]]
        self.assertIn("叶片产能", labels_b)
        self.assertIn("塔架重量", labels_b)
        self.assertNotIn("招标编号", labels_b)
        self.assertEqual(table_b["factSpecsRef"]["version"], 2)

        # 绑定元数据经 facts 元信息可查（审计入口）
        facts_a = self.client.get(f"/api/technical/projects/{project_a}/gaps/facts")
        self.assertEqual(facts_a.status_code, 200, facts_a.text)
        self.assertEqual(facts_a.json()["specsRuleId"], rule_a)
        self.assertEqual(facts_a.json()["specsVersion"], 1)
        self.assertTrue(facts_a.json()["specsSha256"])

    def test_upload_persists_immutable_version_files(self) -> None:
        project_id = self._create_project("版本审计项目")
        base = Path(self.temp_dir.name)
        v1_path = _build_xlsx(base / "v1.xlsx", ["招标编号"])
        v2_path = _build_xlsx(base / "v2.xlsx", ["塔架重量"])

        upload_v1 = self._upload_specs(project_id, v1_path, "v1.xlsx").json()
        upload_v2 = self._upload_specs(project_id, v2_path, "v2.xlsx").json()

        # 两版各自落盘，文件互不相同
        project_dir = settings.fact_specs_versions_dir / project_id
        version_files = sorted(project_dir.glob("*.json"))
        self.assertEqual(len(version_files), 2)

        # 历史版本可从数据卷读回（重启后绑定不丢的持久化层），且内容不可变：
        # v2 上传后 v1 仍是旧规则快照
        record_v1 = load_fact_spec_version(project_id, upload_v1["ruleId"])
        self.assertIsNotNone(record_v1)
        self.assertEqual(record_v1["version"], 1)
        self.assertEqual(record_v1["projectId"], project_id)
        self.assertTrue(record_v1["uploadedBy"])
        self.assertTrue(record_v1["uploadedAt"])
        self.assertEqual(
            record_v1["sha256"], hashlib.sha256(v1_path.read_bytes()).hexdigest()
        )
        self.assertEqual([spec["label"] for spec in record_v1["specs"]], ["招标编号"])

        record_v2 = load_fact_spec_version(project_id, upload_v2["ruleId"])
        self.assertEqual(record_v2["version"], 2)
        self.assertEqual([spec["label"] for spec in record_v2["specs"]], ["塔架重量"])

        # 项目绑定随 gap_state 持久化，重新 require 仍在
        binding = store._require(project_id)["gap_state"]["factSpecs"]
        self.assertEqual(binding["ruleId"], upload_v2["ruleId"])
        self.assertEqual(binding["version"], 2)

    def test_unbound_project_falls_back_to_default_specs(self) -> None:
        specs, meta = resolve_project_specs({})
        self.assertEqual(meta["source"], FACT_SPECS_SOURCE_DEFAULT)
        self.assertEqual(len(specs), len(load_specs()))
        self.assertGreater(len(specs), 0)

    def test_curator_manifest_uses_bound_project_specs(self) -> None:
        binding_specs = [
            {
                "seq": 1,
                "key": "P-001",
                "label": "项目专属字段",
                "reviewLabel": "",
                "sourceKind": "material",
                "referenceFile": "项目定制/专属材料.xlsx",
                "valueRequired": True,
                "needsConfirmation": False,
            }
        ]
        gap_state = {
            "factSpecs": {
                "ruleId": "fsr-testa12345",
                "version": 3,
                "fileName": "项目专属实时表.xlsx",
                "uploadedAt": "2026-07-28T00:00:00Z",
                "uploadedBy": "测试人",
                "sha256": "ab" * 32,
                "specs": binding_specs,
            },
            "projectFactTable": {
                "schemaVersion": "bid-project-fact-table-v2",
                "fields": [
                    {
                        "id": "FACT-0001",
                        "key": "项目专属字段",
                        "label": "项目专属字段",
                        "value": "",
                        "status": "unextracted",
                        "specKey": "P-001",
                        "specSeq": 1,
                        "sourceRefs": [],
                        "notes": "",
                    }
                ],
            },
        }
        project = {"id": "P-BIND", "name": "绑定项目", "parse_storage": {}}
        with (
            patch.object(curator, "_curator_materials", lambda project, gap_state: []),
            patch.object(curator, "_curator_work_dir", lambda project: Path(self.temp_dir.name)),
        ):
            manifest, _ = curator.build_fact_curator_manifest(project, gap_state, {})

        # referenceFile 来自项目绑定版本，不是系统公共清单
        self.assertEqual(
            manifest["projectFactTable"]["fields"][0]["referenceFile"], "项目定制/专属材料.xlsx"
        )
        self.assertEqual(manifest["factSpecsRef"]["ruleId"], "fsr-testa12345")
        self.assertEqual(manifest["factSpecsRef"]["version"], 3)

    def test_curator_manifest_falls_back_to_default_specs(self) -> None:
        global_specs = load_specs()
        self.assertTrue(global_specs)
        first = next(spec for spec in global_specs if spec.get("key"))
        gap_state = {
            "projectFactTable": {
                "schemaVersion": "bid-project-fact-table-v2",
                "fields": [
                    {
                        "id": "FACT-0001",
                        "key": "x",
                        "label": str(first.get("label") or "x"),
                        "value": "",
                        "status": "unextracted",
                        "specKey": str(first["key"]),
                        "specSeq": int(first.get("seq") or 0),
                        "sourceRefs": [],
                        "notes": "",
                    }
                ],
            },
        }
        project = {"id": "P-DEFAULT", "name": "默认回落项目", "parse_storage": {}}
        with (
            patch.object(curator, "_curator_materials", lambda project, gap_state: []),
            patch.object(curator, "_curator_work_dir", lambda project: Path(self.temp_dir.name)),
        ):
            manifest, _ = curator.build_fact_curator_manifest(project, gap_state, {})

        self.assertEqual(manifest["factSpecsRef"]["source"], FACT_SPECS_SOURCE_DEFAULT)
        self.assertEqual(
            manifest["projectFactTable"]["fields"][0]["referenceFile"],
            str(first.get("referenceFile") or ""),
        )


if __name__ == "__main__":
    unittest.main()
