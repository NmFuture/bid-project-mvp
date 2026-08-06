"""正文一键填写后台任务：范围收敛、并发配置、失败记录、素材精简路径。"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from app.services.technical_body_fill_job import (
    DEFAULT_BODY_FILL_CONCURRENCY,
    body_fill_concurrency,
    body_fill_running,
    body_fill_state,
    collect_body_fill_targets,
    empty_body_fill_state,
)
from app.services.technical_gap_ai_fill import fact_table_drives_placeholders

WORD_SKILL = "bid-tech-word-placeholder-filler"
TABLE_SKILL = "bid-tech-table-filler"


def _item(gap_id: str, *tasks: dict, decision: str = "fill_required", **extra) -> dict:
    return {"id": gap_id, "title": f"目录项 {gap_id}", "decision": decision, "fillTasks": list(tasks), **extra}


def _task(task_id: str, skill: str = WORD_SKILL, status: str = "pending") -> dict:
    return {"id": task_id, "skill": skill, "status": status}


def _gap_state(*items: dict) -> dict:
    return {"plan": {"items": list(items)}}


class CollectTargetsTests(unittest.TestCase):
    def test_only_word_fill_tasks_are_batched(self) -> None:
        # 附表由另一条线负责，一键正文不碰它
        state = _gap_state(_item("G1", _task("T1", WORD_SKILL), _task("T2", TABLE_SKILL)))
        targets = collect_body_fill_targets(state, {})
        self.assertEqual([t["fillTaskId"] for t in targets], ["T1"])

    def test_completed_tasks_skipped_unless_rerun(self) -> None:
        state = _gap_state(_item("G1", _task("T1", status="completed"), _task("T2")))
        self.assertEqual([t["fillTaskId"] for t in collect_body_fill_targets(state, {})], ["T2"])
        self.assertEqual(
            [t["fillTaskId"] for t in collect_body_fill_targets(state, {"rerun": True})], ["T1", "T2"]
        )

    def test_gap_ids_narrow_the_batch(self) -> None:
        # 前端按当前标签筛选传 gapIds，批量只跑筛出来的那些
        state = _gap_state(_item("G1", _task("T1")), _item("G2", _task("T2")))
        targets = collect_body_fill_targets(state, {"gapIds": ["G2"]})
        self.assertEqual([t["gapId"] for t in targets], ["G2"])

    def test_non_fill_required_and_title_only_items_excluded(self) -> None:
        state = _gap_state(
            _item("G1", _task("T1"), decision="ready"),
            _item("G2", _task("T2"), titleOnly=True),
            _item("G3", _task("T3")),
        )
        self.assertEqual([t["gapId"] for t in collect_body_fill_targets(state, {})], ["G3"])


class StateTests(unittest.TestCase):
    def test_empty_state_is_idle(self) -> None:
        self.assertEqual(empty_body_fill_state()["status"], "idle")
        self.assertFalse(body_fill_running({}))

    def test_running_covers_queued_and_running(self) -> None:
        for status in ("queued", "running"):
            self.assertTrue(body_fill_running({"bodyFillState": {"status": status}}))
        for status in ("idle", "succeeded", "partial", "failed"):
            self.assertFalse(body_fill_running({"bodyFillState": {"status": status}}))

    def test_state_is_deep_copied(self) -> None:
        gap_state = {"bodyFillState": {"status": "running", "errors": [{"gapId": "G1"}]}}
        snapshot = body_fill_state(gap_state)
        snapshot["errors"].append({"gapId": "G2"})
        self.assertEqual(len(gap_state["bodyFillState"]["errors"]), 1)


class ConcurrencyTests(unittest.TestCase):
    def test_default_is_local_safe(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TECHNICAL_BODY_FILL_CONCURRENCY", None)
            self.assertEqual(body_fill_concurrency(), DEFAULT_BODY_FILL_CONCURRENCY)

    def test_env_override_is_clamped(self) -> None:
        for raw, expected in (("8", 8), ("0", 1), ("999", 16), ("不是数字", DEFAULT_BODY_FILL_CONCURRENCY)):
            with mock.patch.dict(os.environ, {"TECHNICAL_BODY_FILL_CONCURRENCY": raw}):
                self.assertEqual(body_fill_concurrency(), expected)


class SpecDrivenFillTests(unittest.TestCase):
    def test_fact_table_with_spec_columns_drives_placeholders(self) -> None:
        table = {"fields": [{"label": "投标机型", "placeholder": "[投标机型，待填写]"}]}
        self.assertTrue(fact_table_drives_placeholders(table))

    def test_target_file_alone_is_enough(self) -> None:
        table = {"fields": [{"label": "投标机型", "targetFile": "客户定制/华能/待填写-x.docx"}]}
        self.assertTrue(fact_table_drives_placeholders(table))

    def test_legacy_fact_table_falls_back_to_material_chain(self) -> None:
        # 历史快照没有清单第 2/3 列：素材照准备，走旧的模糊匹配链路
        self.assertFalse(fact_table_drives_placeholders({"fields": [{"label": "投标机型", "value": "EW10.0-220"}]}))
        self.assertFalse(fact_table_drives_placeholders({}))


class RunBodyFillJobTests(unittest.TestCase):
    """跑批本体：进度逐条回写、单条失败不中断整批、失败原因落到目录项上。"""

    def setUp(self) -> None:
        self.project = {
            "id": "PRJ-BODY",
            "gap_state": _gap_state(
                _item("G1", _task("T1")),
                _item("G2", _task("T2")),
                _item("G3", _task("T3")),
            ),
        }
        patches = [
            mock.patch(
                "app.services.technical_body_fill_job.require_technical_gap_project_for_update",
                side_effect=lambda project_id: self.project,
            ),
            mock.patch("app.services.technical_body_fill_job.persist_technical_gap_project", lambda project: None),
            mock.patch(
                "app.services.technical_body_fill_job.ensure_technical_gap_state",
                side_effect=lambda project: project["gap_state"],
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _run(self, fill_side_effect) -> dict:
        with mock.patch(
            "app.services.technical_gap_actions.run_technical_ai_fill_for_gap",
            side_effect=fill_side_effect,
        ):
            from app.services.technical_body_fill_job import run_body_fill_job

            run_body_fill_job("PRJ-BODY", {"operator": "测试用户"})
        return self.project["gap_state"]["bodyFillState"]

    def test_all_success_reports_totals(self) -> None:
        calls: list[str] = []
        state = self._run(lambda project, gap_id, data, **kwargs: calls.append(gap_id))

        self.assertEqual(sorted(calls), ["G1", "G2", "G3"])
        self.assertEqual(state["status"], "succeeded")
        self.assertEqual((state["total"], state["done"], state["succeeded"], state["failed"]), (3, 3, 3, 0))

    def test_one_failure_does_not_stop_the_batch(self) -> None:
        def fill(project, gap_id, data, **kwargs):
            if gap_id == "G2":
                raise RuntimeError("素材缺失")

        state = self._run(fill)

        self.assertEqual(state["status"], "partial")
        self.assertEqual((state["succeeded"], state["failed"]), (2, 1))
        self.assertEqual([error["gapId"] for error in state["errors"]], ["G2"])
        self.assertIn("素材缺失", state["errors"][0]["message"])

    def test_failure_is_recorded_on_the_item_for_red_marking(self) -> None:
        self._run(lambda project, gap_id, data, **kwargs: (_ for _ in ()).throw(RuntimeError("填写失败")) if gap_id == "G1" else None)

        failed = next(item for item in self.project["gap_state"]["plan"]["items"] if item["id"] == "G1")
        self.assertEqual(failed["fillError"]["fillTaskId"], "T1")
        self.assertIn("填写失败", failed["fillError"]["message"])

    def test_empty_batch_finishes_without_running_anything(self) -> None:
        self.project["gap_state"] = _gap_state(_item("G1", _task("T1", TABLE_SKILL)))
        state = self._run(lambda *args, **kwargs: None)

        self.assertEqual(state["status"], "succeeded")
        self.assertEqual(state["total"], 0)
        self.assertIn("没有待填写", state["message"])


if __name__ == "__main__":
    unittest.main()
