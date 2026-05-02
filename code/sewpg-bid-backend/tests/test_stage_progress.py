from __future__ import annotations

import unittest

from app.services.store import AppStore


class StageProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = AppStore(storage_backend="memory")
        self.store.reset_for_tests()

    def test_get_stages_returns_collapsed_workflow_steps(self) -> None:
        project = self.store.create_project({"name": "阶段进度条项目"})

        stages = self.store.get_stages(project["id"])

        self.assertEqual([stage["name"] for stage in stages], ["模板与目录", "审核目录", "缺口处理", "生成标书", "共创", "导出"])
        self.assertEqual([stage["routeStageId"] for stage in stages], [1, 3, 4, 7, 9, 10])
        self.assertEqual(stages[0]["stageIds"], [1, 2])
        self.assertEqual(stages[2]["stageIds"], [4, 5, 6])
        self.assertEqual(stages[3]["stageIds"], [7, 8])

    def test_collapsed_stage_status_tracks_internal_stage_ranges(self) -> None:
        project = self.store.create_project({"name": "阶段进度条项目"})
        project_id = project["id"]

        self.store.update_stage(project_id, 3, {"status": "active"})
        stages = self.store.get_stages(project_id)
        self.assertEqual([stage["status"] for stage in stages], ["completed", "active", "pending", "pending", "pending", "pending"])

        self.store.update_stage(project_id, 6, {"status": "completed"})
        stages = self.store.get_stages(project_id)
        self.assertEqual([stage["status"] for stage in stages], ["completed", "completed", "completed", "active", "pending", "pending"])


if __name__ == "__main__":
    unittest.main()
