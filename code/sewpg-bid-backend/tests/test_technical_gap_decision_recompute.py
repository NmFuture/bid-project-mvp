from __future__ import annotations

import unittest

from app.services.technical_gap_domain import recompute_technical_gap_decisions


def _base_item(**overrides):
    item = {
        "id": "GAP-0001",
        "title": "示例章节",
        "decision": "material_required",
        "status": "missing",
        "usage": "",
        "resolvedArtifacts": [],
        "fillTasks": [],
        "candidateMaterials": [],
    }
    item.update(overrides)
    return item


class RecomputeTechnicalGapDecisionsTests(unittest.TestCase):
    def test_resolved_artifact_forces_ready(self) -> None:
        """已经产出确认过的产物（选中/上传/AI填写完成）→ 决策终审为 ready，不管之前是什么决策。"""
        item = _base_item(
            decision="fill_required",
            status="needs_input",
            candidateMaterials=[{"id": "RAW-1"}],
            resolvedArtifacts=[{"id": "ART-1", "source": "material_library"}],
        )
        plan = {"items": [item]}
        changed = recompute_technical_gap_decisions(plan)
        self.assertEqual(changed, 1)
        self.assertEqual(item["decision"], "ready")
        self.assertEqual(item["status"], "resolved")

    def test_pending_fill_task_keeps_fill_required(self) -> None:
        """有未完成的 fillTasks（附表或正文「待填写」模板）→ 始终是 fill_required，不受候选是否存在影响。"""
        item = _base_item(
            decision="fill_required",
            status="needs_input",
            usage="section_fill",
            fillTasks=[{"id": "FILL-1", "status": "pending"}],
            candidateMaterials=[{"id": "RAW-1"}],
        )
        plan = {"items": [item]}
        changed = recompute_technical_gap_decisions(plan)
        self.assertEqual(changed, 0)
        self.assertEqual(item["decision"], "fill_required")

    def test_unreviewed_ai_artifact_requires_review(self) -> None:
        item = _base_item(
            decision="fill_required",
            status="needs_input",
            fillTasks=[{"id": "FILL-1", "status": "completed"}],
            resolvedArtifacts=[{"id": "ART-AI", "source": "ai_fill", "s7Ready": False}],
        )
        plan = {"items": [item]}

        changed = recompute_technical_gap_decisions(plan)

        self.assertEqual(changed, 1)
        self.assertEqual(item["decision"], "review_required")
        self.assertEqual(item["status"], "needs_input")

    def test_legacy_needs_review_ai_artifact_is_not_trusted_by_s7_ready_flag(self) -> None:
        item = _base_item(
            decision="ready",
            status="resolved",
            fillTasks=[{"id": "FILL-1", "status": "completed"}],
            resolvedArtifacts=[
                {
                    "id": "ART-AI",
                    "source": "ai_fill",
                    "s7Ready": True,
                    "qualityReport": {"status": "needs_review"},
                }
            ],
        )
        plan = {"items": [item]}

        recompute_technical_gap_decisions(plan)

        self.assertEqual(item["decision"], "review_required")
        self.assertEqual(item["status"], "needs_input")

    def test_ready_ai_artifact_does_not_hide_another_pending_fill_task(self) -> None:
        item = _base_item(
            decision="ready",
            status="resolved",
            fillTasks=[
                {"id": "FILL-1", "status": "completed"},
                {"id": "FILL-2", "status": "pending"},
            ],
            resolvedArtifacts=[
                {
                    "id": "ART-AI",
                    "source": "ai_fill",
                    "s7Ready": True,
                    "qualityReport": {"status": "passed"},
                }
            ],
        )
        plan = {"items": [item]}

        changed = recompute_technical_gap_decisions(plan)

        self.assertEqual(changed, 1)
        self.assertEqual(item["decision"], "fill_required")
        self.assertEqual(item["status"], "needs_input")

    def test_completed_fill_tasks_do_not_block_review(self) -> None:
        """fillTasks 全部 completed 但还没产出 resolvedArtifacts → 不再算「需要处理」，按候选情况继续走终审。"""
        item = _base_item(
            decision="fill_required",
            status="needs_input",
            usage="section_fill",
            fillTasks=[{"id": "FILL-1", "status": "completed"}],
            candidateMaterials=[{"id": "RAW-1"}],
        )
        plan = {"items": [item]}
        recompute_technical_gap_decisions(plan)
        self.assertEqual(item["decision"], "review_required")

    def test_unconfirmed_candidates_become_review_required(self) -> None:
        """纯候选、无 fillTasks、无 resolvedArtifacts（主题召回/文件级候选待人工选）→ 激活 review_required。"""
        item = _base_item(
            decision="fill_required",
            status="needs_input",
            usage="section_fill",
            candidateMaterials=[{"id": "RAW-1", "topicRelevance": 0.45}],
        )
        plan = {"items": [item]}
        changed = recompute_technical_gap_decisions(plan)
        self.assertEqual(changed, 1)
        self.assertEqual(item["decision"], "review_required")
        self.assertEqual(item["status"], "needs_input")

    def test_no_candidates_stays_material_required(self) -> None:
        """既无候选也无产物 → 保持 material_required（人工补料），不受终审影响。"""
        item = _base_item(decision="material_required", status="missing")
        plan = {"items": [item]}
        changed = recompute_technical_gap_decisions(plan)
        self.assertEqual(changed, 0)
        self.assertEqual(item["decision"], "material_required")

    def test_ready_with_matched_material_is_not_swept_into_review_required(self) -> None:
        """已经有现成可用素材的「固定素材」（decision=ready，matchedMaterials 非空）即使还带着
        备选 candidateMaterials，也不能被终审误判成 review_required —— 这是本次改造最容易踩的坑。
        """
        item = _base_item(
            decision="ready",
            status="matched",
            usage="section_merge",
            candidateMaterials=[{"id": "RAW-2"}],  # 备选，不是待选定候选
        )
        item["matchedMaterials"] = [{"id": "RAW-1"}]
        plan = {"items": [item]}
        changed = recompute_technical_gap_decisions(plan)
        self.assertEqual(changed, 0)
        self.assertEqual(item["decision"], "ready")

    def test_structural_item_untouched(self) -> None:
        """结构性目录项（不需要素材）保持原样，不参与终审改写。"""
        item = _base_item(decision="ready", status="structural", usage="structural")
        plan = {"items": [item]}
        changed = recompute_technical_gap_decisions(plan)
        self.assertEqual(changed, 0)
        self.assertEqual(item["decision"], "ready")

    def test_covered_by_parent_fill_required_without_candidates_untouched(self) -> None:
        """子章节继承父章节「需要AI填写」的决策，自身无 fillTasks/candidateMaterials → 保持不变，
        等父章节的 AI 填写任务完成后由父项自身的终审逻辑推动。
        """
        item = _base_item(
            decision="fill_required",
            status="needs_input",
            usage="covered_by_parent",
        )
        plan = {"items": [item]}
        changed = recompute_technical_gap_decisions(plan)
        self.assertEqual(changed, 0)
        self.assertEqual(item["decision"], "fill_required")

    def test_non_dict_items_are_skipped(self) -> None:
        plan = {"items": [None, "not-a-dict", _base_item()]}
        changed = recompute_technical_gap_decisions(plan)
        self.assertEqual(changed, 0)


if __name__ == "__main__":
    unittest.main()
