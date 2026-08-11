"""正文一键填写后台任务：范围收敛、并发配置、失败记录、素材精简路径。"""
from __future__ import annotations

import copy
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from app.core.config import settings
from app.services.technical_body_fill_job import (
    apply_filled_gap_item,
    body_fill_running,
    body_fill_state,
    collect_body_fill_skips,
    collect_body_fill_targets,
    empty_body_fill_state,
)
from app.services.technical_gap_ai_fill import (
    apply_technical_ai_fill_result,
    fact_table_drives_placeholders,
    fact_table_spec_coverage,
    require_spec_driven_fact_table,
)

WORD_SKILL = "bid-tech-word-placeholder-filler"
TABLE_SKILL = "bid-tech-table-filler"

SPEC_DRIVEN_FACT_TABLE = {
    "fields": [{"label": "投标机型", "value": "EW10.0-220", "placeholder": "[投标机型，待填写]"}]
}


def _item(gap_id: str, *tasks: dict, decision: str = "fill_required", **extra) -> dict:
    return {"id": gap_id, "title": f"目录项 {gap_id}", "decision": decision, "fillTasks": list(tasks), **extra}


def _task(task_id: str, skill: str = WORD_SKILL, status: str = "pending") -> dict:
    return {"id": task_id, "skill": skill, "status": status}


def _gap_state(*items: dict, fact_table: dict | None = None) -> dict:
    return {
        "plan": {"items": list(items)},
        "projectFactTable": SPEC_DRIVEN_FACT_TABLE if fact_table is None else fact_table,
    }


def _fill_result(
    gap_id: str,
    fill_task_id: str,
    *,
    skill: str = WORD_SKILL,
    unfilled: int = 0,
    quality: str = "passed",
    artifact_id: str = "",
    created_at: str = "2026-08-11T00:00:00Z",
) -> dict:
    """compute_technical_ai_fill 的可 JSON 化结果包（测试替身）。"""
    artifact = {
        "id": artifact_id or f"ART-{gap_id}-{fill_task_id}",
        "fileName": f"{gap_id}_AI填写.docx",
        "skill": skill,
        "fillTaskId": fill_task_id,
    }
    return {
        "gapId": gap_id,
        "fillTaskId": fill_task_id,
        "skill": skill,
        "artifact": artifact,
        "artifacts": [artifact],
        "qualityReport": {"status": quality},
        "unfilledFieldCount": unfilled,
        "createdAt": created_at,
        "operator": "测试用户",
    }


class CollectTargetsTests(unittest.TestCase):
    def test_word_and_table_fill_tasks_are_batched_word_first(self) -> None:
        # 一键填写同时覆盖正文与附表；正文在前、附表在后（附表单条更重，让正文结果先落出来）
        state = _gap_state(
            _item("G1", _task("T1", WORD_SKILL), _task("T2", TABLE_SKILL)),
            _item("G2", _task("T3", WORD_SKILL)),
        )
        targets = collect_body_fill_targets(state, {})
        self.assertEqual([t["fillTaskId"] for t in targets], ["T1", "T3", "T2"])

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


class SourceRoutingSkipTests(unittest.TestCase):
    """#228：manual_required / missing_source 的附表任务不进一键填写清单，原因在 skips 可见。"""

    @staticmethod
    def _routing_item(gap_id: str, task_id: str, status: str) -> dict:
        item = _item(gap_id, _task(task_id, TABLE_SKILL))
        item["appendixTasks"] = [
            {"id": f"APP-{gap_id}", "sourceRouting": {"source": "appendix_source_matrix", "status": status}}
        ]
        return item

    def test_manual_required_and_missing_source_excluded_with_reason(self) -> None:
        state = _gap_state(
            self._routing_item("G1", "T1", "manual_required"),
            self._routing_item("G2", "T2", "missing_source"),
            _item("G3", _task("T3", TABLE_SKILL)),
        )
        targets = collect_body_fill_targets(state, {})
        self.assertEqual([t["fillTaskId"] for t in targets], ["T3"])
        skips = collect_body_fill_skips(state, {})
        self.assertEqual([s["fillTaskId"] for s in skips], ["T1", "T2"])
        self.assertTrue(all(s["reason"] for s in skips))

    def test_tender_parse_fields_and_matched_not_skipped(self) -> None:
        state = _gap_state(
            self._routing_item("G1", "T1", "tender_parse_fields"),
            self._routing_item("G2", "T2", "matched"),
        )
        self.assertEqual([t["fillTaskId"] for t in collect_body_fill_targets(state, {})], ["T1", "T2"])
        self.assertEqual(collect_body_fill_skips(state, {}), [])

    def test_word_fill_tasks_never_skipped_by_routing(self) -> None:
        state = _gap_state(self._routing_item("G1", "T1", "manual_required"), _item("G2", _task("T2", WORD_SKILL)))
        # 附表任务被拦，同项/其他项的正文任务不受影响
        self.assertEqual([t["fillTaskId"] for t in collect_body_fill_targets(state, {})], ["T2"])


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


class SpecDrivenFillTests(unittest.TestCase):
    def test_fact_table_with_spec_columns_drives_placeholders(self) -> None:
        table = {"fields": [{"label": "投标机型", "placeholder": "[投标机型，待填写]"}]}
        self.assertTrue(fact_table_drives_placeholders(table))

    def test_target_file_alone_is_enough(self) -> None:
        table = {"fields": [{"label": "投标机型", "targetFile": "客户定制/华能/待填写-x.docx"}]}
        self.assertTrue(fact_table_drives_placeholders(table))

    def test_legacy_fact_table_has_no_spec_columns(self) -> None:
        self.assertFalse(fact_table_drives_placeholders({"fields": [{"label": "投标机型", "value": "EW10.0-220"}]}))
        self.assertFalse(fact_table_drives_placeholders({}))

    def test_coverage_counts_fields_with_spec_columns(self) -> None:
        table = {
            "fields": [
                {"label": "A", "placeholder": "[A，待填写]"},
                {"label": "B", "targetFile": "待填写-x.docx"},
                {"label": "C"},
            ]
        }
        self.assertEqual(fact_table_spec_coverage(table), (3, 2))
        self.assertEqual(fact_table_spec_coverage({}), (0, 0))


class RequireSpecDrivenFactTableTests(unittest.TestCase):
    """清单元数据缺失时正文填写必须显式失败，不再静默回退到旧的模糊匹配链路。"""

    def test_no_fields_asks_for_fact_table(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            require_spec_driven_fact_table({})
        self.assertIn("事实表", str(ctx.exception))

    def test_zero_coverage_reports_field_count_and_asks_for_spec_upload(self) -> None:
        table = {"fields": [{"label": f"字段{index}", "value": "x"} for index in range(148)]}
        with self.assertRaises(RuntimeError) as ctx:
            require_spec_driven_fact_table(table)
        message = str(ctx.exception)
        self.assertIn("148", message)
        self.assertIn("重新上传", message)

    def test_partial_coverage_passes(self) -> None:
        # 缺列的字段会在填写报告里记成 not_in_spec 并标黄，可见且不会填错值，入口不拦
        table = {"fields": [{"label": "A", "placeholder": "[A，待填写]"}, {"label": "B"}]}
        require_spec_driven_fact_table(table)


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
        self.mutate_mock = mock.patch(
            "app.services.technical_body_fill_job.mutate_technical_gap_project",
            # 写回走 CAS 重放封装：测试里直接把改动作用在同一份 project 上即可
            side_effect=lambda project_id, mutate, **kwargs: mutate(self.project),
        ).start()
        patches = [
            mock.patch(
                "app.services.technical_body_fill_job.require_technical_gap_project_for_update",
                side_effect=lambda project_id: self.project,
            ),
            mock.patch(
                "app.services.technical_body_fill_job.ensure_technical_gap_state",
                side_effect=lambda project: project["gap_state"],
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(mock.patch.stopall)

    def _run(self, compute_side_effect) -> dict:
        with mock.patch(
            "app.services.technical_gap_ai_fill.compute_technical_ai_fill",
            side_effect=compute_side_effect,
        ):
            from app.services.technical_body_fill_job import run_body_fill_job

            run_body_fill_job("PRJ-BODY", {"operator": "测试用户"})
        return self.project["gap_state"]["bodyFillState"]

    @staticmethod
    def _compute_ok(calls: list[str] | None = None):
        def compute(project, gap_id, data, **kwargs):
            if calls is not None:
                calls.append(gap_id)
            return _fill_result(gap_id, str(data.get("fillTaskId") or ""))

        return compute

    def test_all_success_reports_totals(self) -> None:
        calls: list[str] = []
        state = self._run(self._compute_ok(calls))

        # 并发执行：完成顺序不确定，只保证每条都跑到
        self.assertEqual(sorted(calls), ["G1", "G2", "G3"])
        self.assertEqual(state["status"], "succeeded")
        self.assertEqual((state["total"], state["done"], state["succeeded"], state["failed"]), (3, 3, 3, 0))

    def test_one_failure_does_not_stop_the_batch(self) -> None:
        def compute(project, gap_id, data, **kwargs):
            if gap_id == "G2":
                raise RuntimeError("素材缺失")
            return _fill_result(gap_id, str(data.get("fillTaskId") or ""))

        state = self._run(compute)

        self.assertEqual(state["status"], "partial")
        self.assertEqual((state["succeeded"], state["failed"]), (2, 1))
        self.assertEqual([error["gapId"] for error in state["errors"]], ["G2"])
        self.assertIn("素材缺失", state["errors"][0]["message"])

    def test_failure_is_recorded_on_the_item_for_red_marking(self) -> None:
        def compute(project, gap_id, data, **kwargs):
            if gap_id == "G1":
                raise RuntimeError("填写失败")
            return _fill_result(gap_id, str(data.get("fillTaskId") or ""))

        self._run(compute)

        failed = next(item for item in self.project["gap_state"]["plan"]["items"] if item["id"] == "G1")
        self.assertEqual(failed["fillError"]["fillTaskId"], "T1")
        self.assertIn("填写失败", failed["fillError"]["message"])

    def test_empty_batch_finishes_without_running_anything(self) -> None:
        self.project["gap_state"] = _gap_state(_item("G1", _task("T1", "bid-tech-other-skill")))
        state = self._run(lambda *args, **kwargs: None)

        self.assertEqual(state["status"], "succeeded")
        self.assertEqual(state["total"], 0)
        self.assertIn("没有待填写", state["message"])

    def test_all_skipped_by_source_rules_reports_pending_materials(self) -> None:
        # 全部被来源规则预过滤：不跑任何填写，状态里能看到「待补资料」原因
        item = _item("G1", _task("T1", TABLE_SKILL))
        item["appendixTasks"] = [
            {"id": "APP-G1", "sourceRouting": {"source": "appendix_source_matrix", "status": "manual_required"}}
        ]
        self.project["gap_state"] = _gap_state(item)
        state = self._run(lambda *args, **kwargs: self.fail("被预过滤的任务不应进入填写"))

        self.assertEqual(state["status"], "succeeded")
        self.assertEqual(state["total"], 0)
        self.assertIn("待补资料", state["message"])
        self.assertEqual([s["fillTaskId"] for s in state["skipped"]], ["T1"])
        self.assertTrue(state["skipped"][0]["reason"])

    def test_fact_table_without_spec_columns_fails_the_whole_batch_upfront(self) -> None:
        # 事实表是项目级单张表：缺清单列时整批一条原因结束，不逐条跑、不逐条标红
        self.project["gap_state"] = _gap_state(
            _item("G1", _task("T1")),
            _item("G2", _task("T2")),
            fact_table={"fields": [{"label": "投标机型", "value": "EW10.0-220"}]},
        )
        calls: list[str] = []
        with self.assertRaises(RuntimeError):
            self._run(self._compute_ok(calls))

        state = self.project["gap_state"]["bodyFillState"]
        self.assertEqual(calls, [])
        self.assertEqual(state["status"], "failed")
        self.assertIn("重新上传", state["message"])
        self.assertFalse(any("fillError" in item for item in self.project["gap_state"]["plan"]["items"]))


class ParallelBodyFillTests(unittest.TestCase):
    """并发执行：compute 真并行、进度计数准确、CAS 重放不丢更新、并发度有上限。"""

    def setUp(self) -> None:
        self.project = {
            "id": "PRJ-BODY",
            "gap_state": _gap_state(
                _item("G1", _task("T1")),
                _item("G2", _task("T2")),
                _item("G3", _task("T3")),
                _item("G4", _task("T4")),
            ),
        }
        self.mutate_mock = mock.patch(
            "app.services.technical_body_fill_job.mutate_technical_gap_project",
            side_effect=lambda project_id, mutate, **kwargs: mutate(self.project),
        ).start()
        patches = [
            mock.patch(
                "app.services.technical_body_fill_job.require_technical_gap_project_for_update",
                side_effect=lambda project_id: self.project,
            ),
            mock.patch(
                "app.services.technical_body_fill_job.ensure_technical_gap_state",
                side_effect=lambda project: project["gap_state"],
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(mock.patch.stopall)

    def _run(self, compute_side_effect) -> dict:
        with mock.patch(
            "app.services.technical_gap_ai_fill.compute_technical_ai_fill",
            side_effect=compute_side_effect,
        ):
            from app.services.technical_body_fill_job import run_body_fill_job

            run_body_fill_job("PRJ-BODY", {"operator": "测试用户"})
        return self.project["gap_state"]["bodyFillState"]

    def test_compute_runs_in_parallel(self) -> None:
        # 4 条任务都进到 compute 里 barrier 才放行；串行执行会超时抛 BrokenBarrierError
        barrier = threading.Barrier(4, timeout=30)
        entered: list[str] = []

        def compute(project, gap_id, data, **kwargs):
            entered.append(gap_id)
            barrier.wait()
            return _fill_result(gap_id, str(data.get("fillTaskId") or ""))

        state = self._run(compute)

        self.assertEqual(sorted(entered), ["G1", "G2", "G3", "G4"])
        self.assertEqual((state["done"], state["succeeded"], state["failed"]), (4, 4, 0))
        self.assertEqual(state["status"], "succeeded")

    def test_progress_counters_accurate_under_concurrency(self) -> None:
        barrier = threading.Barrier(4, timeout=30)

        def compute(project, gap_id, data, **kwargs):
            barrier.wait()
            if gap_id == "G3":
                raise RuntimeError("素材缺失")
            return _fill_result(gap_id, str(data.get("fillTaskId") or ""))

        state = self._run(compute)

        self.assertEqual((state["total"], state["done"], state["succeeded"], state["failed"]), (4, 4, 3, 1))
        self.assertEqual(state["status"], "partial")
        self.assertEqual([error["gapId"] for error in state["errors"]], ["G3"])

    def test_cas_replay_keeps_concurrent_writes_without_duplicates(self) -> None:
        # 模拟 postgres CAS：第一次 apply 写回时判定冲突（另一操作同时改了别的目录项），
        # 回滚后基于最新状态重放。最终 apply 结果与并发写都要在，且重放不产生重复。
        # 进入填写阶段（compute 被调用）后的第一次 mutate 一定是某条结果的 apply 写回。
        filling = {"entered": False}
        injected = {"done": False}

        def cas_mutate(project_id, mutate, **kwargs):
            for _ in range(8):
                snapshot = copy.deepcopy(self.project)
                result = mutate(self.project)
                if injected["done"] or not filling["entered"]:
                    return result
                injected["done"] = True
                # 冲突：回滚本次写回，先落一笔「并发写」，再循环重放 mutate
                self.project.clear()
                self.project.update(snapshot)
                for entry in self.project["gap_state"]["plan"]["items"]:
                    if entry["id"] == "G2":
                        entry["reviewNotes"] = ["并发写加的备注"]
            raise AssertionError("CAS 重放未收敛")

        def compute(project, gap_id, data, **kwargs):
            filling["entered"] = True
            return _fill_result(gap_id, str(data.get("fillTaskId") or ""))

        self.mutate_mock.side_effect = cas_mutate

        state = self._run(compute)

        self.assertTrue(injected["done"])
        self.assertEqual((state["done"], state["succeeded"], state["failed"]), (4, 4, 0))
        items = {entry["id"]: entry for entry in self.project["gap_state"]["plan"]["items"]}
        for gap_id in ("G1", "G2", "G3", "G4"):
            entry = items[gap_id]
            task = entry["fillTasks"][0]
            self.assertEqual(task["status"], "completed")
            self.assertEqual(len(entry["resolvedArtifacts"]), 1)
        self.assertEqual(items["G2"]["reviewNotes"], ["并发写加的备注"])

    def test_concurrency_clamped_to_max(self) -> None:
        recorded: list[int] = []

        class PoolSpy(ThreadPoolExecutor):
            def __init__(self, max_workers=None, **kwargs):
                recorded.append(max_workers)
                super().__init__(max_workers=max_workers, **kwargs)

        with (
            mock.patch.object(settings, "body_fill_concurrency", 100),
            mock.patch("app.services.technical_body_fill_job.ThreadPoolExecutor", PoolSpy),
        ):
            self._run(RunBodyFillJobTests._compute_ok())

        self.assertEqual(recorded, [8])

    def test_concurrency_one_runs_every_target(self) -> None:
        calls: list[str] = []
        with mock.patch.object(settings, "body_fill_concurrency", 1):
            state = self._run(RunBodyFillJobTests._compute_ok(calls))

        # 并发度 1 时退化为按清单顺序串行
        self.assertEqual(calls, ["G1", "G2", "G3", "G4"])
        self.assertEqual((state["done"], state["succeeded"], state["failed"]), (4, 4, 0))


class ApplyTechnicalAiFillResultTests(unittest.TestCase):
    """apply 的幂等与重跑语义：重复 apply 不叠加，新结果（重填）正常覆盖。"""

    def test_repeated_apply_is_idempotent(self) -> None:
        project = {"gap_state": _gap_state(_item("G1", _task("T1")))}
        result = _fill_result("G1", "T1", unfilled=2, quality="needs_review")

        apply_technical_ai_fill_result(project, result)
        apply_technical_ai_fill_result(project, result)

        item = project["gap_state"]["plan"]["items"][0]
        self.assertEqual(len(item["resolvedArtifacts"]), 1)
        self.assertEqual(item["reviewNotes"].count("AI 填写仍有未填字段：2 项"), 1)
        self.assertEqual(item["reviewNotes"].count("AI 填写质量验收未达标，请人工复核或补充事实表后重填。"), 1)

    def test_rerun_with_new_result_applies_again(self) -> None:
        project = {"gap_state": _gap_state(_item("G1", _task("T1")))}
        first = _fill_result("G1", "T1", unfilled=1, artifact_id="ART-G1-T1-a", created_at="2026-08-11T00:00:00Z")
        second = _fill_result("G1", "T1", unfilled=1, artifact_id="ART-G1-T1-b", created_at="2026-08-11T01:00:00Z")

        apply_technical_ai_fill_result(project, first)
        apply_technical_ai_fill_result(project, second)

        item = project["gap_state"]["plan"]["items"][0]
        task = item["fillTasks"][0]
        self.assertEqual(task["outputArtifactId"], "ART-G1-T1-b")
        self.assertEqual(task["completedAt"], "2026-08-11T01:00:00Z")
        # 同一 fillTask 的旧产物被替换，不叠加
        self.assertEqual(len(item["resolvedArtifacts"]), 1)
        self.assertEqual(item["resolvedArtifacts"][0]["id"], "ART-G1-T1-b")
        # 重填是两次独立填写，未填字段提示各记一条
        self.assertEqual(item["reviewNotes"].count("AI 填写仍有未填字段：1 项"), 2)

    def test_apply_rejects_unknown_gap(self) -> None:
        project = {"gap_state": _gap_state(_item("G1", _task("T1")))}
        with self.assertRaises(KeyError):
            apply_technical_ai_fill_result(project, _fill_result("G9", "T9"))


class RunAsyncThreadingTests(unittest.TestCase):
    """_run_async 走共享常驻 loop：并发批填的 worker 线程同时调用时不挂死、不串 loop。

    回归背景：每线程各开 asyncio.run 时，共享 AsyncEngine 的 asyncpg 连接跨 loop
    等待会永久挂起（生产实测正文模板下载卡死 2 小时+）。
    """

    def test_concurrent_calls_from_worker_threads(self) -> None:
        import asyncio  # 局部 import：测试文件主流程用不到

        from app.services.technical_gap_ai_fill import _run_async

        async def probe(value: int) -> int:
            await asyncio.sleep(0.01)
            return value * 2

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda n: _run_async(probe(n)), range(8)))

        self.assertEqual(sorted(results), [n * 2 for n in range(8)])

    def test_error_propagates_to_caller(self) -> None:
        from app.services.technical_gap_ai_fill import _run_async

        async def boom() -> None:
            raise RuntimeError("下载失败")

        with self.assertRaises(RuntimeError):
            _run_async(boom())


class ApplyFilledGapItemMergeTests(unittest.TestCase):
    """#229：apply_filled_gap_item 改为 fillTask/产物级合并，同项其他字段的并发新值不丢。"""

    def _project(self, latest_item: dict) -> dict:
        return {"gap_state": _gap_state(latest_item)}

    def test_merge_preserves_concurrent_changes_on_same_item(self) -> None:
        latest = _item(
            "G1",
            {"id": "T1", "skill": TABLE_SKILL, "status": "pending"},
            {"id": "T2", "skill": TABLE_SKILL, "status": "running", "note": "并发改动"},
            usage="concurrent_new",
            reviewNotes=["并发新增备注"],
            resolvedArtifacts=[
                {"id": "ART-OTHER", "fillTaskId": "T2", "skill": TABLE_SKILL, "fileName": "other.docx"}
            ],
        )
        # 填写开始时的旧快照：T1 已完成，其他字段都是旧值
        filled = _item(
            "G1",
            {
                "id": "T1",
                "skill": TABLE_SKILL,
                "status": "completed",
                "outputArtifactId": "ART-1",
                "completedAt": "2026-08-11T00:00:00Z",
            },
            {"id": "T2", "skill": TABLE_SKILL, "status": "pending"},
            status="resolved",
            qualityStatus="passed",
            qualityReport={"status": "passed"},
            resolvedAt="2026-08-11T00:00:00Z",
            resolvedSource="G1_AI填写.docx",
            usage="old_value",
            reviewNotes=["AI 填写仍有未填字段：1 项"],
            resolvedArtifacts=[{"id": "ART-1", "fillTaskId": "T1", "skill": TABLE_SKILL, "fileName": "G1_AI填写.docx"}],
        )
        project = self._project(latest)

        apply_filled_gap_item(project, "G1", filled, fill_task_id="T1")

        merged = project["gap_state"]["plan"]["items"][0]
        # 本次填写写的字段取结果值
        self.assertEqual(merged["status"], "resolved")
        self.assertEqual(merged["qualityStatus"], "passed")
        tasks = {task["id"]: task for task in merged["fillTasks"]}
        self.assertEqual(tasks["T1"]["status"], "completed")
        self.assertEqual(tasks["T1"]["outputArtifactId"], "ART-1")
        # 同项其他字段/任务的并发新值保留
        self.assertEqual(merged["usage"], "concurrent_new")
        self.assertEqual(tasks["T2"]["status"], "running")
        self.assertEqual(tasks["T2"]["note"], "并发改动")
        # 产物按任务合并：其他任务的产物保留，本次产物追加
        artifact_ids = [artifact["id"] for artifact in merged["resolvedArtifacts"]]
        self.assertEqual(artifact_ids, ["ART-OTHER", "ART-1"])
        # 备注追加合并：并发新增与本次新加都在
        self.assertEqual(merged["reviewNotes"], ["并发新增备注", "AI 填写仍有未填字段：1 项"])

    def test_merge_without_task_id_falls_back_to_resolved_at(self) -> None:
        latest = _item("G1", {"id": "T1", "skill": TABLE_SKILL, "status": "pending"})
        filled = _item(
            "G1",
            {
                "id": "T1",
                "skill": TABLE_SKILL,
                "status": "completed",
                "outputArtifactId": "ART-1",
                "completedAt": "2026-08-11T00:00:00Z",
            },
            status="resolved",
            resolvedAt="2026-08-11T00:00:00Z",
            resolvedArtifacts=[{"id": "ART-1", "fillTaskId": "T1", "skill": TABLE_SKILL, "fileName": "x.docx"}],
        )
        project = self._project(latest)

        apply_filled_gap_item(project, "G1", filled)

        merged = project["gap_state"]["plan"]["items"][0]
        self.assertEqual(merged["fillTasks"][0]["status"], "completed")
        self.assertEqual([a["id"] for a in merged["resolvedArtifacts"]], ["ART-1"])

    def test_unknown_gap_raises(self) -> None:
        project = self._project(_item("G1", _task("T1")))
        with self.assertRaises(KeyError):
            apply_filled_gap_item(project, "G9", _item("G9", _task("T9")), fill_task_id="T9")


if __name__ == "__main__":
    unittest.main()


class EnrichFactTableTests(unittest.TestCase):
    """历史事实表补清单第 2/3 列：老项目不重建也能走精确定位链路。"""

    def setUp(self) -> None:
        from app.services import technical_gap_ai_fill as module

        self.module = module
        self.specs = [
            {"key": "投标机型", "placeholder": "[投标机型，待填写]", "targetFile": "客户定制/华能/待填写-x.docx"},
        ]
        patch = mock.patch.object(module, "resolve_fact_specs", side_effect=lambda: (self.specs, {}))
        patch.start()
        self.addCleanup(patch.stop)

    def test_missing_columns_are_filled_from_current_specs(self) -> None:
        table = {"fields": [{"label": "投标机型", "specKey": "投标机型", "value": "EW10.0-220"}]}
        enriched = self.module.enrich_fact_table_with_spec_columns(table, {})

        self.assertEqual(enriched["fields"][0]["placeholder"], "[投标机型，待填写]")
        self.assertTrue(self.module.fact_table_drives_placeholders(enriched))
        # 原表不被就地改写，取值也一个都没动
        self.assertNotIn("placeholder", table["fields"][0])
        self.assertEqual(enriched["fields"][0]["value"], "EW10.0-220")

    def test_existing_columns_are_left_alone(self) -> None:
        table = {"fields": [{"specKey": "投标机型", "placeholder": "[机型，待填写]", "targetFile": "别的.docx"}]}
        enriched = self.module.enrich_fact_table_with_spec_columns(table, {})

        self.assertEqual(enriched["fields"][0]["placeholder"], "[机型，待填写]")

    def test_unknown_spec_key_is_skipped(self) -> None:
        table = {"fields": [{"specKey": "清单里没有的字段", "value": "x"}]}
        enriched = self.module.enrich_fact_table_with_spec_columns(table, {})

        self.assertFalse(self.module.fact_table_drives_placeholders(enriched))
