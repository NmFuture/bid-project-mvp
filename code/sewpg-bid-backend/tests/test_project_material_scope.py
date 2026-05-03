from __future__ import annotations

import unittest

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

    def test_materials_path_returns_project_readable_scopes(self) -> None:
        create_response = self.client.post(
            "/api/projects",
            json={
                "name": "华能项目素材范围验证",
                "customerName": "华能集团",
                "bidType": "技术标",
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

        scope_response = self.client.get(f"/api/projects/{project_id}/materials-path")

        self.assertEqual(scope_response.status_code, 200)
        payload = scope_response.json()
        self.assertEqual(
            payload["paths"],
            [
                "通用素材/技术标",
                "客户素材/华能集团/技术标",
                "项目素材/MAT-HN-001/技术标",
            ],
        )
        self.assertEqual([item["key"] for item in payload["readableScopes"]], ["standard", "customer", "project"])
        self.assertEqual(payload["identity"]["customerId"], "CUST-HUANENG")
        self.assertEqual(payload["identity"]["projectId"], "MAT-HN-001")


if __name__ == "__main__":
    unittest.main()
