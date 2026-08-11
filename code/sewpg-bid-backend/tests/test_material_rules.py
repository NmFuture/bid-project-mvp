from __future__ import annotations

"""素材库「规则」tab 规则管理接口（/api/technical/materials/rules/...）测试。"""

import json
import tempfile
import unittest
from pathlib import Path

import openpyxl
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services.auth_service import current_user
from app.services.store import store
from app.services.technical_fact_field_specs import clear_specs_cache, load_specs
from app.services.technical_fact_spec_global import (
    GLOBAL_FACT_SPECS_PROJECT_ID,
    global_fact_specs_archive_path,
    global_fact_specs_meta_path,
)
from app.services.technical_fact_spec_import import EXPECTED_HEADER

MATRIX_HEADER = ["客户", "表格", "项目定制", "标准文件", "其他"]
TEST_USER = {"id": "u-rules", "name": "规则测试用户"}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _build_specs_xlsx(path: Path, rows: list[tuple[str, str]], header: list[str] | None = None) -> Path:
    """rows: (实际要填写的字段, 引用文件) 列表，引用文件决定 sourceKind。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header if header is not None else EXPECTED_HEADER)
    for index, (label, reference_file) in enumerate(rows, start=1):
        ws.append([index, "招标文件-技术规范书", "第一章 1.1", label, "", "", reference_file])
    wb.save(path)
    return path


def _build_matrix_xlsx(path: Path, rows: list[list[str]], header: list[str] | None = None) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header if header is not None else MATRIX_HEADER)
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


class _MaterialRulesTestBase(unittest.TestCase):
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

    def _create_project(self) -> str:
        response = self.client.post(
            "/api/technical/projects",
            json={"name": "规则管理测试项目", "customerName": "华能"},
        )
        response.raise_for_status()
        return response.json()["id"]

    def _upload_specs(self, path: Path, filename: str = "事实表清单.xlsx"):
        with path.open("rb") as handle:
            return self.client.post(
                "/api/technical/materials/rules/fact-specs",
                files={"file": (filename, handle, XLSX_MIME)},
            )


class MaterialRulesFactSpecsTests(_MaterialRulesTestBase):
    def test_upload_success_applies_override_and_archives(self) -> None:
        xlsx_path = _build_specs_xlsx(
            Path(self.temp_dir.name) / "事实表清单.xlsx",
            [("招标编号", "招标文件/招标公告"), ("总装机容量", "项目定制/工程量清单")],
        )
        content = xlsx_path.read_bytes()

        response = self._upload_specs(xlsx_path)

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["specTotal"], 2)
        self.assertTrue(payload["override"])
        self.assertEqual(payload["fileName"], "事实表清单.xlsx")
        self.assertTrue(payload["uploadedAt"])

        # override 生效：load_specs 读到上传的 2 条
        self.assertEqual(len(load_specs()), 2)
        self.assertTrue(settings.fact_specs_override_path.is_file())

        # 原表存档与元数据 sidecar 落盘
        self.assertEqual(global_fact_specs_archive_path().read_bytes(), content)
        meta = json.loads(global_fact_specs_meta_path().read_text(encoding="utf-8"))
        self.assertEqual(meta["fileName"], "事实表清单.xlsx")
        self.assertEqual(meta["uploadedBy"], TEST_USER["name"])
        self.assertEqual(meta["specTotal"], 2)
        self.assertTrue(meta["uploadedAt"])
        self.assertTrue(meta["sha256"])

        # _global 不可变版本写入审计链
        version_dir = settings.fact_specs_versions_dir / GLOBAL_FACT_SPECS_PROJECT_ID
        version_files = sorted(version_dir.glob("*.json"))
        self.assertEqual(len(version_files), 1)
        record = json.loads(version_files[0].read_text(encoding="utf-8"))
        self.assertEqual(record["projectId"], GLOBAL_FACT_SPECS_PROJECT_ID)
        self.assertEqual(record["version"], 1)
        self.assertEqual(record["specTotal"], 2)
        self.assertEqual(record["uploadedBy"], TEST_USER["name"])

    def test_upload_rejects_non_xlsx(self) -> None:
        bad_path = Path(self.temp_dir.name) / "清单.txt"
        bad_path.write_text("not an xlsx", encoding="utf-8")

        response = self._upload_specs(bad_path, filename="清单.txt")

        self.assertEqual(response.status_code, 400, response.text)
        self.assertFalse(settings.fact_specs_override_path.exists())
        self.assertFalse(global_fact_specs_archive_path().exists())

    def test_upload_rejects_invalid_content(self) -> None:
        xlsx_path = _build_specs_xlsx(
            Path(self.temp_dir.name) / "坏表头.xlsx",
            [("招标编号", "招标文件/招标公告")],
            header=["A", "B", "C", "D", "E", "F", "G"],
        )

        response = self._upload_specs(xlsx_path, filename="坏表头.xlsx")

        self.assertEqual(response.status_code, 400, response.text)
        self.assertFalse(settings.fact_specs_override_path.exists())
        self.assertFalse(global_fact_specs_archive_path().exists())

    def test_get_without_override_reports_repo_default(self) -> None:
        response = self.client.get("/api/technical/materials/rules/fact-specs")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["source"], "repo-default")
        self.assertEqual(payload["specTotal"], len(load_specs()))

    def test_get_with_override_reports_meta(self) -> None:
        xlsx_path = _build_specs_xlsx(
            Path(self.temp_dir.name) / "事实表清单.xlsx",
            [("招标编号", "招标文件/招标公告")],
        )
        self._upload_specs(xlsx_path).raise_for_status()

        response = self.client.get("/api/technical/materials/rules/fact-specs")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["source"], "override")
        self.assertEqual(payload["fileName"], "事实表清单.xlsx")
        self.assertEqual(payload["specTotal"], 1)
        self.assertEqual(payload["uploadedBy"], TEST_USER["name"])

    def test_download_404_then_200(self) -> None:
        missing = self.client.get("/api/technical/materials/rules/fact-specs/download")
        self.assertEqual(missing.status_code, 404, missing.text)

        xlsx_path = _build_specs_xlsx(
            Path(self.temp_dir.name) / "事实表清单.xlsx",
            [("招标编号", "招标文件/招标公告")],
        )
        self._upload_specs(xlsx_path).raise_for_status()

        response = self.client.get("/api/technical/materials/rules/fact-specs/download")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.content, xlsx_path.read_bytes())
        self.assertIn("attachment", response.headers.get("content-disposition", ""))


class MaterialRulesAppendixSourceMatrixTests(_MaterialRulesTestBase):
    def _upload_matrix(self, project_id: str, path: Path, filename: str = "填写文件来源.xlsx"):
        with path.open("rb") as handle:
            return self.client.post(
                "/api/technical/materials/rules/appendix-source-matrix",
                params={"projectId": project_id},
                files={"file": (filename, handle, XLSX_MIME)},
            )

    def test_upload_get_download_roundtrip(self) -> None:
        project_id = self._create_project()
        xlsx_path = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "填写文件来源.xlsx",
            [["华能", "附表C.1 总体技术参数与规格", "", "机型参数表", ""]],
        )

        upload = self._upload_matrix(project_id, xlsx_path)
        self.assertEqual(upload.status_code, 200, upload.text)
        self.assertEqual(upload.json()["rowCount"], 1)
        self.assertEqual(upload.json()["fileName"], "填写文件来源.xlsx")

        meta_response = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix",
            params={"projectId": project_id},
        )
        self.assertEqual(meta_response.status_code, 200, meta_response.text)
        meta = meta_response.json()
        self.assertEqual(meta["fileName"], "填写文件来源.xlsx")
        self.assertEqual(meta["rowCount"], 1)

        download = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix/download",
            params={"projectId": project_id},
        )
        self.assertEqual(download.status_code, 200, download.text)
        self.assertEqual(download.content, xlsx_path.read_bytes())

    def test_download_404_when_not_uploaded(self) -> None:
        project_id = self._create_project()

        download = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix/download",
            params={"projectId": project_id},
        )
        self.assertEqual(download.status_code, 404, download.text)

        meta_response = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix",
            params={"projectId": project_id},
        )
        self.assertEqual(meta_response.status_code, 200, meta_response.text)
        self.assertEqual(meta_response.json(), {})

    def test_unknown_project_returns_404(self) -> None:
        xlsx_path = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "填写文件来源.xlsx",
            [["华能", "附表C.1 总体技术参数与规格", "", "机型参数表", ""]],
        )

        upload = self._upload_matrix("P-MISSING", xlsx_path)
        self.assertEqual(upload.status_code, 404, upload.text)

        meta_response = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix",
            params={"projectId": "P-MISSING"},
        )
        self.assertEqual(meta_response.status_code, 404, meta_response.text)

        download = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix/download",
            params={"projectId": "P-MISSING"},
        )
        self.assertEqual(download.status_code, 404, download.text)


if __name__ == "__main__":
    unittest.main()
