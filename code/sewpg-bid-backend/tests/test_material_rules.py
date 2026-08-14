from __future__ import annotations

"""素材库「规则」tab 规则管理接口（/api/technical/materials/rules/...）测试。

- 事实表清单（全局）：SQL 为唯一事实来源，保存时重写 override JSON 派生缓存；
- 附表填写规则（按客户）：customerName 维度存取/导入/导出，旧 projectId 端点仅保留兼容。
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import openpyxl
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.core.config import settings
from app.models import async_session
from app.services.auth_service import current_user
from app.services.store import store
from app.services.technical_appendix_source_matrix import parse_appendix_source_matrix
from app.services.technical_fact_field_specs import clear_specs_cache, load_specs
from app.services.technical_fact_spec_global import (
    GLOBAL_FACT_SPECS_PROJECT_ID,
    global_fact_specs_archive_path,
    global_fact_specs_meta_path,
)
from app.services.technical_fact_spec_import import EXPECTED_HEADER, import_specs
from app.services.technical_rules_store import ensure_technical_rules_tables

MATRIX_HEADER = ["客户", "表格", "项目定制", "标准文件", "其他"]
TEST_USER = {"id": "u-rules", "name": "规则测试用户"}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _build_specs_xlsx(path: Path, rows: list[tuple[str, str]], header: list[str] | None = None) -> Path:
    """rows: (字段名, 引用文件) 列表；字段名写进占位符内容列，导入时剥离得出。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header if header is not None else EXPECTED_HEADER)
    for index, (label, reference_file) in enumerate(rows, start=1):
        ws.append(
            [index, "待填写", "标准文件", "招标文件-技术规范书", f"[{label}，待填写]", reference_file]
        )
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


def _reset_rule_tables() -> None:
    """规则表跨用例共享测试库，每个用例前清空，保证客户规则隔离。"""

    async def _run() -> None:
        async with async_session() as session:
            await ensure_technical_rules_tables(session)
            await session.execute(text("DELETE FROM technical_appendix_rule_rows"))
            await session.execute(text("DELETE FROM technical_appendix_rule_meta"))
            await session.execute(text("DELETE FROM technical_fact_spec_rows"))
            await session.commit()

    asyncio.run(_run())


def _spec(seq: int, label: str, reference_file: str = "招标文件/招标公告") -> dict:
    return {
        "seq": seq,
        "key": f"key-{seq}",
        "label": label,
        "reviewLabel": "",
        "targetFile": "招标文件-技术规范书",
        "sourceFile": "招标文件-技术规范书",
        "placeholder": f"第一章 1.{seq}",
        "note": "",
        "needsConfirmation": False,
        "referenceFile": reference_file,
        "valueRequired": True,
        "sourceKind": "tender",
        "aliases": [],
    }


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
        _reset_rule_tables()
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

        # SQL 落库：rows 接口能读到同样的 2 条
        rows_response = self.client.get("/api/technical/materials/rules/fact-specs/rows")
        self.assertEqual(rows_response.status_code, 200, rows_response.text)
        db_specs = rows_response.json()["specs"]
        self.assertEqual(len(db_specs), 2)
        self.assertEqual(db_specs[0]["label"], "招标编号")

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

    def test_get_without_override_reports_none(self) -> None:
        response = self.client.get("/api/technical/materials/rules/fact-specs")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        # 仓库不再自带默认清单：未上传时 source=none、specTotal=0
        self.assertEqual(payload["source"], "none")
        self.assertEqual(payload["specTotal"], 0)

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

    def test_rows_empty_when_db_empty_and_no_override(self) -> None:
        response = self.client.get("/api/technical/materials/rules/fact-specs/rows")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["specs"], [])

    def test_rows_fallback_to_legacy_override_when_db_empty(self) -> None:
        # SQL 改造前上传的清单只有 override JSON：rows 接口要回落到它，保证老数据可编辑
        legacy = [_spec(1, "招标编号"), _spec(2, "总装机容量", "项目定制/工程量清单")]
        settings.fact_specs_override_path.parent.mkdir(parents=True, exist_ok=True)
        settings.fact_specs_override_path.write_text(
            json.dumps(legacy, ensure_ascii=False), encoding="utf-8"
        )
        clear_specs_cache()

        response = self.client.get("/api/technical/materials/rules/fact-specs/rows")

        self.assertEqual(response.status_code, 200, response.text)
        specs = response.json()["specs"]
        self.assertEqual(len(specs), 2)
        self.assertTrue(specs[0]["key"])
        self.assertTrue(specs[0]["label"])

    def test_put_rows_roundtrip_and_override_regenerated(self) -> None:
        specs = [_spec(1, "招标编号"), _spec(2, "总装机容量", "项目定制/工程量清单")]

        put_response = self.client.put(
            "/api/technical/materials/rules/fact-specs/rows", json={"specs": specs}
        )
        self.assertEqual(put_response.status_code, 200, put_response.text)
        self.assertEqual(put_response.json()["specTotal"], 2)

        rows_response = self.client.get("/api/technical/materials/rules/fact-specs/rows")
        self.assertEqual(rows_response.status_code, 200, rows_response.text)
        self.assertEqual(rows_response.json()["specs"], specs)

        # override JSON 派生缓存已重写，同步消费链立即生效
        self.assertTrue(settings.fact_specs_override_path.is_file())
        self.assertEqual([spec["label"] for spec in load_specs()], ["招标编号", "总装机容量"])

        # 元数据接口反映 SQL 记录数
        meta = self.client.get("/api/technical/materials/rules/fact-specs").json()
        self.assertEqual(meta["source"], "override")
        self.assertEqual(meta["specTotal"], 2)

    def test_put_rows_rejects_missing_key_or_label(self) -> None:
        response = self.client.put(
            "/api/technical/materials/rules/fact-specs/rows",
            json={"specs": [{"key": "", "label": "招标编号"}]},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("key", response.json()["detail"])

        response = self.client.put(
            "/api/technical/materials/rules/fact-specs/rows",
            json={"specs": [{"key": "k1", "label": ""}]},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("label", response.json()["detail"])

    def test_export_xlsx_is_reimportable(self) -> None:
        specs = [_spec(1, "招标编号"), _spec(2, "总装机容量", "项目定制/工程量清单")]
        self.client.put(
            "/api/technical/materials/rules/fact-specs/rows", json={"specs": specs}
        ).raise_for_status()

        response = self.client.get("/api/technical/materials/rules/fact-specs/export")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("attachment", response.headers.get("content-disposition", ""))

        exported = Path(self.temp_dir.name) / "导出清单.xlsx"
        exported.write_bytes(response.content)
        reimported = import_specs(exported)
        self.assertEqual([spec["label"] for spec in reimported], ["招标编号", "总装机容量"])


class MaterialRulesAppendixSourceMatrixTests(_MaterialRulesTestBase):
    def _upload_matrix(self, customer: str, path: Path, filename: str = "填写文件来源.xlsx"):
        with path.open("rb") as handle:
            return self.client.post(
                "/api/technical/materials/rules/appendix-source-matrix",
                params={"customerName": customer},
                files={"file": (filename, handle, XLSX_MIME)},
            )

    def test_upload_filters_rows_to_customer_and_isolates(self) -> None:
        xlsx_path = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "填写文件来源.xlsx",
            [
                ["华能", "附表C.1 总体技术参数与规格", "", "机型参数表", ""],
                ["华能", "附表B.5 培训内容和计划表", "", "", "响应招标文件填写"],
                ["大唐", "附表A.1 投标机型总方案信息表", "工程量清单", "", ""],
            ],
        )

        upload = self._upload_matrix("华能", xlsx_path)
        self.assertEqual(upload.status_code, 200, upload.text)
        payload = upload.json()
        # 只取属于华能的 2 行
        self.assertEqual(payload["rowCount"], 2)
        self.assertEqual(payload["fileName"], "填写文件来源.xlsx")
        self.assertTrue(payload["uploadedAt"])
        self.assertIn("applied", payload)

        meta = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix",
            params={"customerName": "华能"},
        )
        self.assertEqual(meta.status_code, 200, meta.text)
        self.assertEqual(meta.json()["rowCount"], 2)
        self.assertEqual(meta.json()["fileName"], "填写文件来源.xlsx")
        self.assertEqual(meta.json()["customerId"], "CUST-HUANENG")
        self.assertEqual(meta.json()["customerName"], "华能集团")

        rows = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix/rows",
            params={"customerName": "华能"},
        )
        self.assertEqual(rows.status_code, 200, rows.text)
        row_list = rows.json()["rows"]
        self.assertEqual(len(row_list), 2)
        self.assertEqual(row_list[0]["tableTitle"], "附表C.1 总体技术参数与规格")
        self.assertEqual(row_list[0]["standardSources"], ["机型参数表"])

        # 按客户隔离：大唐名下看不到华能的行
        other_meta = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix",
            params={"customerName": "大唐"},
        )
        self.assertEqual(other_meta.json(), {})
        other_rows = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix/rows",
            params={"customerName": "大唐"},
        )
        self.assertEqual(other_rows.json(), {"rows": []})

    def test_upload_zero_match_returns_400(self) -> None:
        xlsx_path = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "填写文件来源.xlsx",
            [["大唐", "附表A.1 投标机型总方案信息表", "工程量清单", "", ""]],
        )

        upload = self._upload_matrix("华能", xlsx_path)
        self.assertEqual(upload.status_code, 400, upload.text)
        self.assertIn("华能", upload.json()["detail"])

    def test_upload_rejects_matrix_without_valid_rows(self) -> None:
        xlsx_path = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "坏表头.xlsx",
            [["华能", "附表C.1 总体技术参数与规格", "", "机型参数表", ""]],
            header=["A", "B", "C", "D", "E"],
        )

        upload = self._upload_matrix("华能", xlsx_path)
        self.assertEqual(upload.status_code, 400, upload.text)

    def test_put_rows_roundtrip_and_replace(self) -> None:
        rows = [
            {
                "tableTitle": "附表C.1 总体技术参数与规格",
                "projectSources": "塔架与基础工程量、风资源评估报告",
                "standardSources": ["机型参数表"],
                "otherSources": "",
            }
        ]
        put_response = self.client.put(
            "/api/technical/materials/rules/appendix-source-matrix/rows",
            params={"customerName": "华能"},
            json={"rows": rows},
        )
        self.assertEqual(put_response.status_code, 200, put_response.text)
        self.assertEqual(put_response.json()["rowCount"], 1)

        got = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix/rows",
            params={"customerName": "华能"},
        ).json()["rows"]
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["tableTitle"], "附表C.1 总体技术参数与规格")
        # 字符串来源按「、」拆分入库
        self.assertEqual(got[0]["projectSources"], ["塔架与基础工程量", "风资源评估报告"])
        self.assertEqual(got[0]["standardSources"], ["机型参数表"])
        self.assertEqual(got[0]["otherSources"], [])

        # 再次保存全量替换
        replace_response = self.client.put(
            "/api/technical/materials/rules/appendix-source-matrix/rows",
            params={"customerName": "华能"},
            json={"rows": [
                {"tableTitle": "附表D.1 功率曲线", "projectSources": [], "standardSources": ["功率曲线"], "otherSources": []},
                {"tableTitle": "附表B.5 培训内容和计划表", "projectSources": [], "standardSources": [], "otherSources": ["响应招标文件填写"]},
            ]},
        )
        self.assertEqual(replace_response.status_code, 200, replace_response.text)
        self.assertEqual(replace_response.json()["rowCount"], 2)
        got = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix/rows",
            params={"customerName": "华能"},
        ).json()["rows"]
        self.assertEqual([row["tableTitle"] for row in got], ["附表D.1 功率曲线", "附表B.5 培训内容和计划表"])

    def test_put_rows_rejects_missing_table_title(self) -> None:
        response = self.client.put(
            "/api/technical/materials/rules/appendix-source-matrix/rows",
            params={"customerName": "华能"},
            json={"rows": [{"tableTitle": "", "standardSources": ["机型参数表"]}]},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("表格", response.json()["detail"])

    def test_export_xlsx_reparseable(self) -> None:
        self.client.put(
            "/api/technical/materials/rules/appendix-source-matrix/rows",
            params={"customerName": "华能"},
            json={"rows": [
                {
                    "tableTitle": "附表C.1 总体技术参数与规格",
                    "projectSources": ["塔架与基础工程量"],
                    "standardSources": ["机型参数表"],
                    "otherSources": ["响应招标文件填写"],
                }
            ]},
        ).raise_for_status()

        response = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix/export",
            params={"customerName": "华能"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("attachment", response.headers.get("content-disposition", ""))

        exported = Path(self.temp_dir.name) / "导出规则.xlsx"
        exported.write_bytes(response.content)
        matrix = parse_appendix_source_matrix(exported)
        self.assertEqual(len(matrix["rows"]), 1)
        row = matrix["rows"][0]
        self.assertEqual(row["customer"], "华能集团")
        self.assertEqual(row["tableTitle"], "附表C.1 总体技术参数与规格")
        self.assertEqual(row["projectSources"], ["塔架与基础工程量"])
        self.assertEqual(row["standardSources"], ["机型参数表"])
        self.assertEqual(row["otherSources"], ["响应招标文件填写"])

    def test_export_404_when_customer_has_no_rules(self) -> None:
        response = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix/export",
            params={"customerName": "华能"},
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_legacy_project_id_upload_returns_410(self) -> None:
        project_id = self._create_project()
        xlsx_path = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "填写文件来源.xlsx",
            [["华能", "附表C.1 总体技术参数与规格", "", "机型参数表", ""]],
        )
        with xlsx_path.open("rb") as handle:
            response = self.client.post(
                "/api/technical/materials/rules/appendix-source-matrix",
                params={"projectId": project_id},
                files={"file": ("填写文件来源.xlsx", handle, XLSX_MIME)},
            )
        self.assertEqual(response.status_code, 410, response.text)

    def test_legacy_project_id_meta_resolves_customer(self) -> None:
        project_id = self._create_project()
        xlsx_path = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "填写文件来源.xlsx",
            [["华能", "附表C.1 总体技术参数与规格", "", "机型参数表", ""]],
        )
        self._upload_matrix("华能", xlsx_path).raise_for_status()

        # 旧 projectId 版 GET 按项目所属客户解析元数据
        meta_response = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix",
            params={"projectId": project_id},
        )
        self.assertEqual(meta_response.status_code, 200, meta_response.text)
        self.assertEqual(meta_response.json()["rowCount"], 1)
        self.assertEqual(meta_response.json()["customerId"], "CUST-HUANENG")

        missing = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix",
            params={"projectId": "P-MISSING"},
        )
        self.assertEqual(missing.status_code, 404, missing.text)

    def test_legacy_project_id_download_roundtrip(self) -> None:
        """项目级上传端点留盘的 xlsx 仍可经旧下载端点取回。"""
        project_id = self._create_project()
        download = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix/download",
            params={"projectId": project_id},
        )
        self.assertEqual(download.status_code, 404, download.text)

        xlsx_path = _build_matrix_xlsx(
            Path(self.temp_dir.name) / "填写文件来源.xlsx",
            [["华能", "附表C.1 总体技术参数与规格", "", "机型参数表", ""]],
        )
        with xlsx_path.open("rb") as handle:
            upload = self.client.post(
                f"/api/technical/projects/{project_id}/appendix-source-matrix",
                files={"file": ("填写文件来源.xlsx", handle, XLSX_MIME)},
            )
        self.assertEqual(upload.status_code, 200, upload.text)

        download = self.client.get(
            "/api/technical/materials/rules/appendix-source-matrix/download",
            params={"projectId": project_id},
        )
        self.assertEqual(download.status_code, 200, download.text)
        self.assertEqual(download.content, xlsx_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
