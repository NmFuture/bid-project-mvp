from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import technical_fact_special_extractors as special_extractors
from app.services.store import store


class FactFieldLevelConfirmTests(unittest.TestCase):
    """逐字段确认 PATCH /api/technical/projects/{pid}/gaps/facts/{field_id} 的契约测试。"""

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

    def _create_project_with_fact_table(self) -> tuple[str, list[dict]]:
        response = self.client.post(
            "/api/technical/projects",
            json={"name": "逐字段确认测试项目", "customerName": "测试业主"},
        )
        response.raise_for_status()
        project_id = response.json()["id"]

        # 直接落一份"识别完成"的 gap 状态，避免跑整套缺口识别流程
        project = store._require(project_id)
        project["identity"] = {"owner": "测试业主", "customerName": "测试业主"}
        project["gap_state"] = {
            "recognitionStatus": "completed",
            "recognizedAt": "2026-07-24T00:00:00",
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

        build_response = self.client.post(f"/api/technical/projects/{project_id}/gaps/facts/build")
        self.assertEqual(build_response.status_code, 200, build_response.text)
        fields = build_response.json()["fields"]
        self.assertTrue(fields)
        return project_id, fields

    def _patch_field(self, project_id: str, field_id: str, payload: dict) -> object:
        return self.client.patch(
            f"/api/technical/projects/{project_id}/gaps/facts/{field_id}",
            json=payload,
        )

    def test_single_field_confirm_only_affects_that_field(self) -> None:
        project_id, fields = self._create_project_with_fact_table()
        target = next(field for field in fields if str(field.get("value") or "").strip())
        before_status = {field["id"]: field["status"] for field in fields}

        response = self._patch_field(project_id, target["id"], {"operator": "测试用户"})

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(set(payload.keys()), {"field", "summary", "status"})
        self.assertEqual(payload["field"]["id"], target["id"])
        self.assertEqual(payload["field"]["status"], "confirmed")
        self.assertEqual(payload["field"]["confirmedBy"], "测试用户")
        self.assertTrue(payload["field"]["confirmedAt"])
        # 表级仍有大量非终态字段，不升级为 confirmed
        self.assertEqual(payload["status"], "draft")
        self.assertEqual(payload["summary"]["confirmedCount"], 1)

        table = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts").json()
        after = {field["id"]: field for field in table["fields"]}
        self.assertEqual(after[target["id"]]["status"], "confirmed")
        for field_id, status in before_status.items():
            if field_id != target["id"]:
                self.assertEqual(after[field_id]["status"], status, field_id)

    def test_not_applicable_status_preserved_on_confirm(self) -> None:
        project_id, fields = self._create_project_with_fact_table()
        target = next(field for field in fields if not str(field.get("value") or "").strip())

        response = self._patch_field(
            project_id,
            target["id"],
            {"status": "not_applicable", "operator": "测试用户"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        field = response.json()["field"]
        self.assertEqual(field["status"], "not_applicable")
        self.assertEqual(response.json()["summary"]["notApplicableCount"], 1)

    def test_confirm_with_value_update(self) -> None:
        project_id, fields = self._create_project_with_fact_table()
        target = next(field for field in fields if not str(field.get("value") or "").strip())

        response = self._patch_field(
            project_id,
            target["id"],
            {"value": "按招标文件要求执行", "operator": "测试用户"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        field = response.json()["field"]
        self.assertEqual(field["value"], "按招标文件要求执行")
        self.assertEqual(field["status"], "confirmed")
        self.assertEqual(field["confirmedBy"], "测试用户")

    def test_missing_field_returns_404(self) -> None:
        project_id, _ = self._create_project_with_fact_table()

        response = self._patch_field(project_id, "FACT-9999", {"operator": "测试用户"})

        self.assertEqual(response.status_code, 404, response.text)

    def test_table_auto_confirmed_when_all_fields_terminal(self) -> None:
        project_id, fields = self._create_project_with_fact_table()
        last_response = None
        for field in fields:
            last_response = self._patch_field(project_id, field["id"], {"operator": "测试用户"})
            self.assertEqual(last_response.status_code, 200, last_response.text)

        payload = last_response.json()
        self.assertEqual(payload["status"], "confirmed")
        summary = payload["summary"]
        self.assertEqual(
            summary["totalCount"],
            summary["confirmedCount"] + summary["missingSourceCount"] + summary["notApplicableCount"],
        )

        table = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts").json()
        self.assertEqual(table["status"], "confirmed")
        self.assertTrue(table["confirmedAt"])
        self.assertEqual(table["confirmedBy"], "测试用户")

    def test_coexists_with_full_table_put(self) -> None:
        project_id, fields = self._create_project_with_fact_table()
        target = fields[0]

        patch_response = self._patch_field(project_id, target["id"], {"operator": "测试用户"})
        self.assertEqual(patch_response.status_code, 200, patch_response.text)

        # 整表确认 PUT 在逐字段确认之后仍可用，且不丢逐字段结果
        table = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts").json()
        put_response = self.client.put(
            f"/api/technical/projects/{project_id}/gaps/facts",
            json={"fields": table["fields"], "confirm": True, "operator": "测试用户"},
        )
        self.assertEqual(put_response.status_code, 200, put_response.text)
        self.assertEqual(put_response.json()["status"], "confirmed")

        # 整表确认之后逐字段 PATCH 仍可用
        again = self._patch_field(
            project_id,
            target["id"],
            {"value": "更新后的取值", "operator": "测试用户"},
        )
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["field"]["value"], "更新后的取值")
        self.assertEqual(again.json()["field"]["status"], "confirmed")
        self.assertEqual(again.json()["status"], "confirmed")


class CertificatePdfSourcePageTests(unittest.TestCase):
    """证书专项抽取：PDF 来源事实的 sourceRef.page 定位（合成分页文本，不读真实 PDF）。"""

    _PAGE1 = "型式认证证书封面，" + "正文。" * 40
    _PAGE2 = "参考风速 42.5 m/s，安全等级 IEC IA。" + "说明。" * 30
    _PAGE3 = "湍流强度 0.14。" + "备注。" * 30

    def _facts_with_mocked_pages(self, file_name: str, pages: list[str] | None) -> list[dict]:
        full_text = "\n\n".join(pages or [])
        material = {"id": "MAT-CERT-1", "name": file_name, "materialTier": "standard"}
        path = Path(file_name)  # 仅取后缀，文本/分页均被 monkeypatch
        with (
            patch.object(special_extractors, "_certificate_text", return_value=full_text),
            patch.object(
                special_extractors,
                "_certificate_pdf_pages",
                return_value=(pages if path.suffix.lower() == ".pdf" else []),
            ),
        ):
            return special_extractors.facts_from_certificate_materials([(material, path)], {})

    def test_pdf_cert_facts_carry_source_page(self) -> None:
        facts = self._facts_with_mocked_pages(
            "EW6.7-220型式认证B.pdf", [self._PAGE1, self._PAGE2, self._PAGE3]
        )
        by_label = {str(fact.get("label")): fact for fact in facts}

        vref = by_label["机型认证10分钟平均极限风速（m/s）"]
        self.assertEqual(vref["sourceRef"]["page"], 2)
        self.assertEqual(by_label["安全等级"]["sourceRef"]["page"], 2)
        self.assertEqual(by_label["湍流强度"]["sourceRef"]["page"], 3)
        # 摘要串事实取首个组成参数（vref）的页码
        self.assertEqual(by_label["设计认证核心风资源参数"]["sourceRef"]["page"], 2)

    def test_docx_cert_facts_have_no_page_key(self) -> None:
        facts = self._facts_with_mocked_pages(
            "EW6.7-220型式认证B.docx", [self._PAGE1, self._PAGE2, self._PAGE3]
        )
        self.assertTrue(facts)
        for fact in facts:
            self.assertNotIn("page", fact["sourceRef"])


if __name__ == "__main__":
    unittest.main()
