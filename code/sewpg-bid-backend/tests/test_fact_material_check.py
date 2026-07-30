from __future__ import annotations

"""素材齐备性预检（material-check）测试：missing/crossProjectCandidates/summary 与 API 链路。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import technical_fact_material_classes as material_classes
from app.services.store import store


def _project() -> dict:
    return {"id": "P-CHK", "name": "本项目"}


def _own_material(material_id: str, name: str) -> dict:
    return {"id": material_id, "name": name, "folderPath": "技术标/项目定制/本项目"}


def _pool_item(material_id: str, name: str, home: str) -> dict:
    return {"id": material_id, "name": name, "folderPath": f"技术标/项目定制/{home}"}


# ---------------------------------------------------------------- 对账逻辑（素材索引桩）


def _stub_index(monkeypatch, materials: list[dict], pool: list[dict]) -> list:
    calls = []
    monkeypatch.setattr(material_classes, "project_fact_material_index", lambda project, gap_state: materials)

    def fake_scan(**kwargs):
        calls.append(kwargs)
        return {"items": pool}

    monkeypatch.setattr(material_classes, "run_async_material_files", fake_scan)
    return calls


def test_missing_classes_report_cross_project_candidates(monkeypatch) -> None:
    calls = _stub_index(
        monkeypatch,
        materials=[_own_material("RAW-W1", "本项目风资源报告.docx")],
        pool=[
            _pool_item("RAW-T1", "乙项目塔架与基础工程量.xlsx", "乙项目"),
            _pool_item("RAW-T2", "本项目塔架工程量.xlsx", "本项目"),  # 本项目素材不作跨项目候选
            _pool_item("RAW-X1", "会议纪要.docx", "丙项目"),  # 无法归类
        ],
    )

    check = material_classes.build_fact_material_check(_project(), {})

    by_class = {item["class"]: item for item in check["classes"]}
    wind = by_class["wind_resource"]
    assert wind["missing"] is False
    assert [item["id"] for item in wind["matched"]] == ["RAW-W1"]
    assert wind["requiredFieldCount"] == 26
    assert wind["crossProjectCandidates"] == []

    tower = by_class["tower_quantity"]
    assert tower["missing"] is True
    assert tower["crossProjectCandidates"] == [
        {
            "id": "RAW-T1",
            "name": "乙项目塔架与基础工程量.xlsx",
            "folderPath": "技术标/项目定制/乙项目",
            "homeProject": "乙项目",
        }
    ]
    # 有缺失类别才扫全库，且只扫一次
    assert len(calls) == 1
    assert calls[0]["folder_path"] == "技术标/项目定制"
    assert calls[0]["recursive"] is True

    assert check["summary"]["missingClasses"] == [
        "tower_quantity",
        "bending_moment",
        "hours_commitment",
        "production_base",
        "cert",
    ]
    assert check["summary"]["affectedFieldCount"] == 38 + 18 + 1 + 4 + 4


def test_all_classes_matched_skips_library_scan(monkeypatch) -> None:
    calls = _stub_index(
        monkeypatch,
        materials=[
            _own_material("RAW-1", "风资源报告.docx"),
            _own_material("RAW-2", "塔架工程量.xlsx"),
            _own_material("RAW-3", "基础弯矩表.xlsx"),
            _own_material("RAW-4", "发电小时数承诺函.docx"),
            _own_material("RAW-5", "生产制造基地专题.docx"),
            _own_material("RAW-6", "型式认证证书.pdf"),
        ],
        pool=[],
    )

    check = material_classes.build_fact_material_check(_project(), {})

    assert calls == []  # 五类全齐 + cert 齐：不做全库扫描
    assert check["summary"] == {"missingClasses": [], "affectedFieldCount": 0}
    assert all(not item["missing"] for item in check["classes"])
    assert all(item["crossProjectCandidates"] == [] for item in check["classes"])


def test_cross_project_candidates_capped_at_five(monkeypatch) -> None:
    pool = [_pool_item(f"RAW-T{i}", f"乙项目塔架工程量{i}.xlsx", "乙项目") for i in range(7)]
    _stub_index(monkeypatch, materials=[], pool=pool)

    check = material_classes.build_fact_material_check(_project(), {})

    tower = next(item for item in check["classes"] if item["class"] == "tower_quantity")
    assert len(tower["crossProjectCandidates"]) == 5
    assert {item["homeProject"] for item in tower["crossProjectCandidates"]} == {"乙项目"}


def test_library_scan_failure_degrades_to_no_candidates(monkeypatch) -> None:
    monkeypatch.setattr(material_classes, "project_fact_material_index", lambda project, gap_state: [])

    def failing_scan(**kwargs):
        raise RuntimeError("mock 素材库不可用")

    monkeypatch.setattr(material_classes, "run_async_material_files", failing_scan)

    check = material_classes.build_fact_material_check(_project(), {})

    assert len(check["summary"]["missingClasses"]) == 6
    assert all(item["crossProjectCandidates"] == [] for item in check["classes"])


# ---------------------------------------------------------------- API 链路


class FactMaterialCheckApiTests(unittest.TestCase):
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
            json={"name": "预检API测试项目", "customerName": "测试业主"},
        )
        response.raise_for_status()
        return response.json()["id"]

    def test_material_check_endpoint(self) -> None:
        project_id = self._create_project()
        with (
            patch.object(
                material_classes,
                "project_fact_material_index",
                return_value=[_own_material("RAW-W1", "风资源报告.docx")],
            ),
            patch.object(
                material_classes,
                "run_async_material_files",
                return_value={"items": [_pool_item("RAW-T1", "乙项目塔架工程量.xlsx", "乙项目")]},
            ),
        ):
            response = self.client.get(f"/api/technical/projects/{project_id}/gaps/facts/material-check")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        by_class = {item["class"]: item for item in payload["classes"]}
        self.assertFalse(by_class["wind_resource"]["missing"])
        self.assertTrue(by_class["tower_quantity"]["missing"])
        self.assertEqual(
            by_class["tower_quantity"]["crossProjectCandidates"][0]["homeProject"],
            "乙项目",
        )
        self.assertIn("tower_quantity", payload["summary"]["missingClasses"])
        self.assertGreater(payload["summary"]["affectedFieldCount"], 0)

    def test_material_check_endpoint_unknown_project_404(self) -> None:
        response = self.client.get("/api/technical/projects/PRJ-NOPE/gaps/facts/material-check")
        self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":
    unittest.main()
