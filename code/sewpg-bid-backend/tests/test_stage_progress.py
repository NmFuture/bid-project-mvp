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
        self.assertEqual([stage["id"] for stage in stages], [1, 2, 3, 4, 5, 6])
        self.assertEqual([stage["routeStageId"] for stage in stages], [1, 2, 3, 4, 5, 6])

    def test_stage_status_tracks_s1_to_s6_steps(self) -> None:
        project = self.store.create_project({"name": "阶段进度条项目"})
        project_id = project["id"]

        self.store.update_stage(project_id, 2, {"status": "active"})
        stages = self.store.get_stages(project_id)
        self.assertEqual([stage["status"] for stage in stages], ["completed", "active", "pending", "pending", "pending", "pending"])

        self.store.update_stage(project_id, 3, {"status": "completed"})
        stages = self.store.get_stages(project_id)
        self.assertEqual([stage["status"] for stage in stages], ["completed", "completed", "completed", "active", "pending", "pending"])

    def test_legacy_stage_is_folded_to_current_s1_to_s6(self) -> None:
        project = self.store.create_project({"name": "历史阶段项目"})
        project_id = project["id"]
        raw_project = self.store._require(project_id)
        raw_project["stageScheme"] = "legacy"
        raw_project["currentStage"] = 9
        self.store._normalize_project_identity(raw_project)

        self.assertEqual(raw_project["stageScheme"], "S0_S6")
        self.assertEqual(raw_project["currentStage"], 5)
        self.assertEqual(self.store.get_project(project_id)["stageLabel"], "共创")

    def test_legacy_stage_update_request_still_maps_to_current_stage(self) -> None:
        project = self.store.create_project({"name": "历史客户端项目"})
        project_id = project["id"]

        self.store.update_stage(project_id, 9, {"status": "completed"})

        detail = self.store.get_project(project_id)
        self.assertEqual(detail["currentStage"], 6)
        self.assertEqual(detail["stageLabel"], "导出")


if __name__ == "__main__":
    unittest.main()
