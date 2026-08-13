from __future__ import annotations

import os
import unittest

import pytest

from app.services.bid_outline_state import complete_directory_generation_state
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
                "技术标/标准文件",
                "技术标/客户定制/华能集团",
                "技术标/项目定制/华能项目素材范围验证",
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
                "bidType": "技术标",
            }
        )
        project_state = store1.require_project_for_update(created["id"])
        complete_directory_generation_state(project_state, {})
        store1.persist_project_state(project_state)

        store2 = AppStore(storage_backend="postgres")
        project = store2.get_project(created["id"])
        directory = store2.get_project_runtime_state(created["id"])["directory_state"]

        self.assertEqual(project["name"], "PostgreSQL 持久化验证")
        self.assertEqual(directory["status"], "completed")

    def test_project_id_continues_after_restart(self) -> None:
        store1 = AppStore(storage_backend="postgres")
        first = store1.create_project({"name": "项目一", "bidType": "技术标"})

        store2 = AppStore(storage_backend="postgres")
        second = store2.create_project({"name": "项目二", "bidType": "技术标"})

        self.assertEqual(first["id"], "PRJ-0001")
        self.assertEqual(second["id"], "PRJ-0002")

    def test_project_id_not_recycled_after_delete_and_restart(self) -> None:
        """删掉最大编号项目再重启，新项目不得拿回该编号。

        编号一旦回收，新项目会落进 /data/documents/{PID} 的残留工作区，读到上一轮的
        tender_review_state.json 后把解析降级成续跑，最终报成功却没有产物。
        复现必须带重启：编号在进程内是递增计数器，不重启看不到回收。
        """
        store1 = AppStore(storage_backend="postgres")
        first = store1.create_project({"name": "项目一", "bidType": "技术标"})
        second = store1.create_project({"name": "项目二", "bidType": "技术标"})
        self.assertEqual(first["id"], "PRJ-0001")
        self.assertEqual(second["id"], "PRJ-0002")

        store1.delete_project(second["id"])

        store2 = AppStore(storage_backend="postgres")
        third = store2.create_project({"name": "项目三", "bidType": "技术标"})

        self.assertNotEqual(third["id"], second["id"])
        self.assertEqual(third["id"], "PRJ-0003")

    def test_project_id_not_recycled_after_deleting_all_projects(self) -> None:
        """把项目删光再重启，编号仍要接着往下发，不能从头开始。"""
        store1 = AppStore(storage_backend="postgres")
        created = [
            store1.create_project({"name": f"项目{index}", "bidType": "技术标"})["id"]
            for index in range(1, 4)
        ]
        self.assertEqual(created, ["PRJ-0001", "PRJ-0002", "PRJ-0003"])

        for project_id in created:
            store1.delete_project(project_id)

        store2 = AppStore(storage_backend="postgres")
        fresh = store2.create_project({"name": "清空后新建", "bidType": "技术标"})

        self.assertNotIn(fresh["id"], created)
        self.assertEqual(fresh["id"], "PRJ-0004")


if __name__ == "__main__":
    unittest.main()
