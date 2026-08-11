from __future__ import annotations

"""填表规则（事实表字段清单）全局唯一 + 版本化测试。

清单与项目无关：规则页上传一份，所有项目按同一张表去各自的招标文件与素材里找值。
覆盖：

- 多个项目共用同一份清单，各自 build 的字段骨架一致；
- 上传新版本后所有项目重建都用新版（不再存在项目各自绑定的旧快照）；
- 每次上传生成不可变版本文件（ruleId/版本号/上传人/时间/sha256），重启后可从数据卷读回；
- 尚未上传清单时事实表建不出来，并提示去规则页上传；
- AI 维护（curator）manifest 按当前生效的全局清单关联 spec。
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
from app.services.auth_service import current_user
from app.services.store import store
from app.services.technical_fact_field_specs import clear_specs_cache, load_specs
from app.services.technical_fact_spec_global import (
    GLOBAL_FACT_SPECS_PROJECT_ID,
    resolve_fact_specs,
)
from app.services.technical_fact_spec_import import EXPECTED_HEADER
from app.services.technical_fact_spec_versions import (
    FACT_SPECS_SOURCE_GLOBAL,
    load_fact_spec_version,
)

TEST_USER = {"id": "u-specs", "name": "清单测试用户"}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _build_xlsx(path: Path, labels: list[str]) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(EXPECTED_HEADER)
    for index, label in enumerate(labels, start=1):
        ws.append([index, "招标文件-技术规范书", "第一章 1.1", label, "", "", "招标文件/技术规范书"])
    wb.save(path)
    return path


class GlobalFactSpecVersionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        self._orig_dirs = (
            settings.uploads_dir,
            settings.documents_dir,
            settings.parsed_dir,
            settings.fact_specs_override_path,
            settings.fact_specs_versions_dir,
        )
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        # conftest 的 autouse 夹具装了一份 148 条清单；这里要从「没有清单」起步
        settings.fact_specs_override_path = base / "documents" / "technical_fact_field_specs.override.json"
        settings.fact_specs_versions_dir = base / "fact_spec_versions"
        settings.ensure_dirs()
        clear_specs_cache()

        store.reset_for_tests()
        app.dependency_overrides[current_user] = lambda: dict(TEST_USER)
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.pop(current_user, None)
        (
            settings.uploads_dir,
            settings.documents_dir,
            settings.parsed_dir,
            settings.fact_specs_override_path,
            settings.fact_specs_versions_dir,
        ) = self._orig_dirs
        clear_specs_cache()
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

    def _upload_specs(self, path: Path, filename: str = "事实表清单.xlsx"):
        with path.open("rb") as handle:
            return self.client.post(
                "/api/technical/materials/rules/fact-specs",
                files={"file": (filename, handle, XLSX_MIME)},
            )

    def _build_facts(self, project_id: str) -> dict:
        response = self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/build")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_all_projects_share_one_global_list(self) -> None:
        project_a = self._create_project("项目A")
        project_b = self._create_project("项目B")
        base = Path(self.temp_dir.name)

        upload = self._upload_specs(_build_xlsx(base / "v1.xlsx", ["招标编号", "总装机容量"]), "v1.xlsx")
        self.assertEqual(upload.status_code, 200, upload.text)

        table_a = self._build_facts(project_a)
        table_b = self._build_facts(project_b)
        spec_labels_a = [field["label"] for field in table_a["fields"] if field.get("specSeq")]
        spec_labels_b = [field["label"] for field in table_b["fields"] if field.get("specSeq")]
        self.assertEqual(spec_labels_a, ["招标编号", "总装机容量"])
        # 骨架同一份；值各找各的，所以只比字段名
        self.assertEqual(spec_labels_a, spec_labels_b)
        self.assertEqual(table_a["factSpecsRef"]["source"], FACT_SPECS_SOURCE_GLOBAL)
        self.assertEqual(table_a["factSpecsRef"]["ruleId"], table_b["factSpecsRef"]["ruleId"])

    def test_new_upload_applies_to_every_project(self) -> None:
        project_id = self._create_project("换版项目")
        base = Path(self.temp_dir.name)

        self._upload_specs(_build_xlsx(base / "v1.xlsx", ["招标编号"]), "v1.xlsx")
        first = self._build_facts(project_id)
        self.assertEqual([f["label"] for f in first["fields"] if f.get("specSeq")], ["招标编号"])

        self._upload_specs(_build_xlsx(base / "v2.xlsx", ["塔架重量"]), "v2.xlsx")
        second = self._build_facts(project_id)
        # 换版即换骨架，不存在"项目还留着旧快照"
        self.assertEqual([f["label"] for f in second["fields"] if f.get("specSeq")], ["塔架重量"])
        self.assertNotEqual(second["factSpecsRef"]["ruleId"], first["factSpecsRef"]["ruleId"])
        self.assertEqual(second["factSpecsRef"]["version"], 2)

    def test_upload_persists_immutable_version_files(self) -> None:
        base = Path(self.temp_dir.name)
        v1_path = _build_xlsx(base / "v1.xlsx", ["招标编号"])
        v2_path = _build_xlsx(base / "v2.xlsx", ["塔架重量"])

        upload_v1 = self._upload_specs(v1_path, "v1.xlsx")
        self.assertEqual(upload_v1.status_code, 200, upload_v1.text)
        upload_v2 = self._upload_specs(v2_path, "v2.xlsx")
        self.assertEqual(upload_v2.status_code, 200, upload_v2.text)

        version_dir = settings.fact_specs_versions_dir / GLOBAL_FACT_SPECS_PROJECT_ID
        self.assertEqual(len(sorted(version_dir.glob("*.json"))), 2)

        _, ref_v2 = resolve_fact_specs()
        self.assertEqual(ref_v2["version"], 2)
        record_v2 = load_fact_spec_version(GLOBAL_FACT_SPECS_PROJECT_ID, ref_v2["ruleId"])
        self.assertIsNotNone(record_v2)
        self.assertEqual([spec["label"] for spec in record_v2["specs"]], ["塔架重量"])
        self.assertEqual(record_v2["sha256"], hashlib.sha256(v2_path.read_bytes()).hexdigest())
        self.assertTrue(record_v2["uploadedBy"])

        # v1 的版本文件不因 v2 上传而改动
        v1_files = [
            path
            for path in version_dir.glob("v0001-*.json")
            if path.is_file()
        ]
        self.assertEqual(len(v1_files), 1)
        record_v1 = load_fact_spec_version(
            GLOBAL_FACT_SPECS_PROJECT_ID, v1_files[0].stem.split("-", 1)[1]
        )
        self.assertEqual([spec["label"] for spec in record_v1["specs"]], ["招标编号"])
        self.assertEqual(record_v1["version"], 1)

    def test_build_is_blocked_until_global_list_uploaded(self) -> None:
        project_id = self._create_project("无清单项目")
        response = self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/build")
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("规则页", response.json()["detail"])

        facts = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts")
        self.assertEqual(facts.status_code, 200, facts.text)
        self.assertFalse(facts.json()["specsImported"])
        self.assertEqual(facts.json()["specTotal"], 0)

    def test_facts_metadata_reports_global_list(self) -> None:
        project_id = self._create_project("审计项目")
        base = Path(self.temp_dir.name)
        self._upload_specs(_build_xlsx(base / "v1.xlsx", ["招标编号"]), "审计用清单.xlsx")

        facts = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts").json()
        self.assertTrue(facts["specsImported"])
        self.assertEqual(facts["specsFileName"], "审计用清单.xlsx")
        self.assertEqual(facts["specTotal"], 1)
        self.assertEqual(facts["specsVersion"], 1)
        self.assertTrue(facts["specsRuleId"])
        self.assertTrue(facts["specsSha256"])

    def test_curator_manifest_uses_global_specs(self) -> None:
        base = Path(self.temp_dir.name)
        self._upload_specs(_build_xlsx(base / "v1.xlsx", ["项目专属字段"]), "v1.xlsx")
        specs = load_specs()
        first = specs[0]
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
        project = {"id": "P-GLOBAL", "name": "全局清单项目", "parse_storage": {}}
        with (
            patch.object(curator, "_curator_materials", lambda project, gap_state: []),
            patch.object(curator, "_curator_work_dir", lambda project: Path(self.temp_dir.name)),
        ):
            manifest, _ = curator.build_fact_curator_manifest(project, gap_state, {})

        self.assertEqual(manifest["factSpecsRef"]["source"], FACT_SPECS_SOURCE_GLOBAL)
        self.assertEqual(
            manifest["projectFactTable"]["fields"][0]["referenceFile"],
            str(first.get("referenceFile") or ""),
        )


if __name__ == "__main__":
    unittest.main()
