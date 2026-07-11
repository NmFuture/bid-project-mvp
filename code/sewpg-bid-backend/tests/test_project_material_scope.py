from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.store import store


class ProjectMaterialScopeRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        store.reset_for_tests(clear_persistent=True)
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")

    def tearDown(self) -> None:
        self.client.close()
        store.reset_for_tests(clear_persistent=True)

    def _auth_headers(self) -> dict[str, str]:
        login = self.client.post("/api/auth/login", json={"email": "admin@sewpg.com", "password": "123456"})
        login.raise_for_status()
        return {"Authorization": f"Bearer {login.json()['token']}"}

    def test_materials_path_returns_project_readable_scopes(self) -> None:
        create_response = self.client.post(
            "/api/technical/projects",
            json={
                "name": "华能项目素材范围验证",
                "customerName": "华能集团",
                "materialCustomerId": "CUST-HUANENG",
                "materialCustomerName": "华能集团",
                "materialProjectMode": "library",
                "materialProjectId": "MAT-HN-001",
                "materialProjectCode": "HN-001",
                "materialProjectName": "华能素材项目",
            },
        )
        create_response.raise_for_status()
        project_id = create_response.json()["id"]

        scope_response = self.client.get(f"/api/technical/projects/{project_id}/materials-path")

        self.assertEqual(scope_response.status_code, 200)
        payload = scope_response.json()
        self.assertEqual(
            payload["paths"],
            [
                "技术标/标准文件",
                "技术标/客户定制/华能集团",
                "技术标/项目定制/MAT-HN-001",
            ],
        )
        self.assertEqual([item["key"] for item in payload["readableScopes"]], ["standard", "customer", "project"])
        self.assertEqual(payload["identity"]["customerId"], "CUST-HUANENG")
        self.assertEqual(payload["identity"]["projectId"], "MAT-HN-001")

    def test_business_materials_path_returns_business_scopes(self) -> None:
        create_response = self.client.post(
            "/api/business/projects",
            json={
                "name": "华能商务标素材范围验证",
                "customerName": "华能集团",
                "materialCustomerId": "CUST-HUANENG",
                "materialCustomerName": "华能集团",
                "materialProjectMode": "library",
                "materialProjectId": "MAT-BIZ-HN-001",
                "materialProjectCode": "BIZ-HN-001",
                "materialProjectName": "华能商务素材项目",
            },
        )
        create_response.raise_for_status()
        project_id = create_response.json()["id"]

        scope_response = self.client.get(f"/api/business/projects/{project_id}/materials-path")

        self.assertEqual(scope_response.status_code, 200)
        payload = scope_response.json()
        self.assertEqual(
            payload["paths"],
            [
                "商务标/通用素材",
                "商务标/客户素材/华能集团",
                "商务标/项目素材/MAT-BIZ-HN-001",
            ],
        )
        self.assertEqual(payload["path"], "商务标/项目素材/MAT-BIZ-HN-001")
        self.assertEqual(payload["bidType"], "商务标")
        self.assertEqual([item["key"] for item in payload["readableScopes"]], ["standard", "customer", "project"])
        self.assertEqual(payload["identity"]["customerId"], "CUST-HUANENG")
        self.assertEqual(payload["identity"]["projectId"], "MAT-BIZ-HN-001")

    def test_business_project_payload_clears_turbine_model_fields(self) -> None:
        response = self.client.post(
            "/api/business/projects",
            json={
                "name": "商务标不应携带风机字段",
                "customerName": "测试业主",
                "turbineModel": {"model": "EW10.0-220"},
                "turbineModels": [{"model": "EW10.0-220", "turbineCount": "10"}],
            },
        )
        response.raise_for_status()

        payload = response.json()
        self.assertEqual(payload["turbineModel"], {})
        self.assertEqual(payload["selectedTurbineModel"], {})
        self.assertEqual(payload["turbineModels"], [])
        self.assertEqual(payload["turbineModelLabel"], "")

    def test_legacy_project_materials_path_endpoint_is_not_registered(self) -> None:
        response = self.client.get("/api/projects/PRJ-LEGACY/materials-path")

        self.assertEqual(response.status_code, 404)

    def test_project_list_filters_participate_review_decision(self) -> None:
        pending = self.client.post(
            "/api/business/projects",
            json={"name": "商务解析暂存", "customerName": "", "reviewDecision": "pending"},
        )
        pending.raise_for_status()
        participate = self.client.post(
            "/api/business/projects",
            json={"name": "商务参与项目", "customerName": "测试业主", "reviewDecision": "participate"},
        )
        participate.raise_for_status()

        response = self.client.get("/api/business/projects?reviewDecision=participate&pageSize=20")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual([item["id"] for item in payload["items"]], [participate.json()["id"]])
        self.assertNotIn(pending.json()["id"], [item["id"] for item in payload["items"]])

    def test_workspace_ocr_task_routes_are_split(self) -> None:
        technical = self.client.post(
            "/api/technical/projects",
            json={"name": "技术标 OCR 路由测试", "customerName": "测试业主"},
        )
        technical.raise_for_status()
        business = self.client.post(
            "/api/business/projects",
            json={"name": "商务标 OCR 路由测试", "customerName": "测试业主"},
        )
        business.raise_for_status()
        headers = self._auth_headers()

        with patch(
            "app.api.routes.technical.technical_ocr_service.list_tasks",
            new=AsyncMock(return_value={"items": [], "total": 0}),
        ) as technical_list:
            technical_response = self.client.get(
                f"/api/technical/projects/{technical.json()['id']}/ocr/tasks",
                headers=headers,
            )
        with patch(
            "app.api.routes.business.business_ocr_service.list_tasks",
            new=AsyncMock(return_value={"items": [], "total": 0}),
        ) as business_list:
            business_response = self.client.get(
                f"/api/business/projects/{business.json()['id']}/ocr/tasks",
                headers=headers,
            )

        self.assertEqual(technical_response.status_code, 200)
        self.assertEqual(business_response.status_code, 200)
        technical_list.assert_awaited_once_with(technical.json()["id"])
        business_list.assert_awaited_once_with(business.json()["id"])

    def test_legacy_project_ocr_endpoint_is_not_registered(self) -> None:
        response = self.client.get("/api/projects/PRJ-LEGACY/ocr/tasks")

        self.assertEqual(response.status_code, 404)

    def test_legacy_project_parse_result_endpoints_are_not_registered(self) -> None:
        self.assertEqual(self.client.get("/api/projects/PRJ-LEGACY/parse-results").status_code, 404)
        self.assertEqual(self.client.post("/api/projects/PRJ-LEGACY/parse-results/upload-and-run").status_code, 404)

    def test_legacy_material_endpoints_are_not_registered(self) -> None:
        self.assertEqual(self.client.get("/api/materials/raw/tree").status_code, 404)
        self.assertEqual(self.client.get("/api/materials/wiki").status_code, 404)


if __name__ == "__main__":
    unittest.main()
