from __future__ import annotations

import os
import unittest

import pytest

from app.services.identity import build_project_material_scope
from app.services.store import AppStore


class ProjectMaterialScopeTests(unittest.TestCase):
    def test_project_material_scope_uses_selected_customer_and_material_project(self) -> None:
        store = AppStore(storage_backend="memory")
        project = store.create_project(
            {
                "name": "华能项目素材范围验证",
                "customerName": "华能集团",
                "bidType": "技术标",
                "materialCustomerId": "CUST-HUANENG",
                "materialCustomerName": "华能集团",
                "materialProjectMode": "library",
                "materialProjectId": "MAT-HN-001",
                "materialProjectCode": "HN-001",
                "materialProjectName": "华能素材项目",
            }
        )

        scope = build_project_material_scope(project)

        self.assertEqual(
            scope["paths"],
            [
                "通用素材/技术标",
                "客户素材/华能集团/技术标",
                "项目素材/MAT-HN-001/技术标",
            ],
        )
        self.assertEqual(scope["identity"]["customerId"], "CUST-HUANENG")
        self.assertEqual(scope["identity"]["projectId"], "MAT-HN-001")


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("BID_RUN_INTEGRATION") != "1", reason="requires PostgreSQL")
class StorePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = AppStore(storage_backend="postgres")
        self.store.reset_for_tests(clear_persistent=True)

    def tearDown(self) -> None:
        self.store.reset_for_tests(clear_persistent=True)

    def test_project_persists_across_postgres_store_restart(self) -> None:
        store1 = AppStore(storage_backend="postgres")
        created = store1.create_project(
            {
                "name": "PostgreSQL 持久化验证",
                "customerName": "测试业主",
            }
        )
        store1.complete_directory_generation(created["id"], {})

        store2 = AppStore(storage_backend="postgres")
        project = store2.get_project(created["id"])
        directory = store2.get_directory_state(created["id"])

        self.assertEqual(project["name"], "PostgreSQL 持久化验证")
        self.assertEqual(directory["status"], "completed")

    def test_project_id_continues_after_restart(self) -> None:
        store1 = AppStore(storage_backend="postgres")
        first = store1.create_project({"name": "项目一"})

        store2 = AppStore(storage_backend="postgres")
        second = store2.create_project({"name": "项目二"})

        self.assertEqual(first["id"], "PRJ-0001")
        self.assertEqual(second["id"], "PRJ-0002")


if __name__ == "__main__":
    unittest.main()
