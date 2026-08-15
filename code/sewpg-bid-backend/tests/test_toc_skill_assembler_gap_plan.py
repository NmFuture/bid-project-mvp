from __future__ import annotations

import json
import tempfile
from pathlib import Path

from toc_skill_helpers import (
    TocSkillScriptTestBase,
    load_assembler_script,
)


class TocSkillScriptTests(TocSkillScriptTestBase):

    def test_bid_assembler_gap_plan_flags_unconfirmed_candidates(self) -> None:
        """1.1/4.7 回归：只有候选素材、未确认 matchedMaterials 时给出显式提示。"""
        build_assembly = load_assembler_script("build_assembly")

        with tempfile.TemporaryDirectory() as tmp:
            gap_plan_path = Path(tmp) / "gap_plan.json"
            gap_plan_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "GAP-0001",
                                "number": "1.1",
                                "title": "上海电气优势简介",
                                "matchedMaterials": [],
                                "candidateMaterials": [
                                    {"id": "RAW-0087", "matchScore": 0.87}
                                ],
                                "resolvedArtifacts": [],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plan = [
                {
                    "chapter_no_flat": "1.1",
                    "chapter_no": "1.1",
                    "title": "上海电气优势简介",
                    "paths": [],
                    "shifts": [],
                    "attach_modes": [],
                    "field_replace": False,
                    "status": "UNMATCHED",
                    "note": "",
                }
            ]

            updated = build_assembly.apply_gap_plan(plan, gap_plan_path)

        self.assertEqual(updated[0]["status"], "UNMATCHED")
        self.assertEqual(updated[0]["paths"], [])
        self.assertIn("候选素材未确认", updated[0]["note"])
        self.assertEqual(updated[0]["gap_plan_item_id"], "GAP-0001")



    def test_bid_assembler_gap_plan_flags_unfinished_ai_fill(self) -> None:
        """1.1/4.7 回归：AI 填写流程未产出 S7-ready 产物时给出显式提示。"""
        build_assembly = load_assembler_script("build_assembly")

        with tempfile.TemporaryDirectory() as tmp:
            gap_plan_path = Path(tmp) / "gap_plan.json"
            gap_plan_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "GAP-0002",
                                "number": "4.7",
                                "title": "项目技术承诺函",
                                "fillTasks": [{"id": "FILL-0002", "status": "pending"}],
                                "matchedMaterials": [],
                                "candidateMaterials": [
                                    {"id": "RAW-0149", "matchScore": 0.87},
                                    {"id": "RAW-0151", "matchScore": 0.85},
                                ],
                                "resolvedArtifacts": [],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plan = [
                {
                    "chapter_no_flat": "4.7",
                    "chapter_no": "4.7",
                    "title": "项目技术承诺函",
                    "paths": [],
                    "shifts": [],
                    "attach_modes": [],
                    "field_replace": False,
                    "status": "UNMATCHED",
                    "note": "",
                }
            ]

            updated = build_assembly.apply_gap_plan(plan, gap_plan_path)

        self.assertEqual(updated[0]["status"], "UNMATCHED")
        self.assertIn("AI 填写未完成", updated[0]["note"])
        self.assertEqual(updated[0]["gap_plan_item_id"], "GAP-0002")



    def test_bid_assembler_gap_plan_matches_appendix_number_plus_title(self) -> None:
        build_assembly = load_assembler_script("build_assembly")

        with tempfile.TemporaryDirectory() as tmp:
            gap_plan_path = Path(tmp) / "gap_plan.json"
            gap_plan_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "GAP-0058",
                                "number": "附表A.1",
                                "title": "投标机型总方案信息表",
                                "fillTasks": [{"id": "FILL-0058", "status": "completed"}],
                                "matchedMaterials": [
                                    {"path": "/tmp/投标机型总方案信息表_待填写.docx"}
                                ],
                                "resolvedArtifacts": [
                                    {
                                        "source": "ai_fill",
                                        "path": "/tmp/投标机型总方案信息表_AI填写.docx",
                                        "s7Ready": True,
                                        "qualityReport": {"status": "passed"},
                                    }
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plan = [
                {
                    "toc_idx": 57,
                    "level": 1,
                    "chapter_no_flat": "",
                    "chapter_no": "",
                    "title": "附表A.1 投标机型总方案信息表",
                    "paths": [],
                    "shifts": [],
                    "attach_modes": [],
                    "field_replace": False,
                    "status": "NEEDS_REVIEW",
                    "note": "招标/模板新增章节，需人工补素材",
                }
            ]

            updated = build_assembly.apply_gap_plan(plan, gap_plan_path)

        self.assertEqual(updated[0]["status"], "MATCHED")
        self.assertEqual(updated[0]["paths"], ["/tmp/投标机型总方案信息表_AI填写.docx"])
        self.assertEqual(updated[0]["gap_plan_item_id"], "GAP-0058")



    def test_bid_assembler_gap_plan_skips_unreviewed_ai_fill_artifact(self) -> None:
        build_assembly = load_assembler_script("build_assembly")

        with tempfile.TemporaryDirectory() as tmp:
            gap_plan_path = Path(tmp) / "gap_plan.json"
            gap_plan_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "GAP-0058",
                                "number": "附表A.1",
                                "title": "投标机型总方案信息表",
                                "fillTasks": [{"id": "FILL-0058", "status": "completed"}],
                                "matchedMaterials": [
                                    {"path": "/tmp/投标机型总方案信息表_待填写.docx"}
                                ],
                                "resolvedArtifacts": [
                                    {
                                        "source": "ai_fill",
                                        "path": "/tmp/未验收_AI填写.docx",
                                        "s7Ready": True,
                                        "qualityReport": {"status": "needs_review"},
                                    }
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plan = [
                {
                    "chapter_no_flat": "附表A.1",
                    "chapter_no": "",
                    "title": "投标机型总方案信息表",
                    "paths": [],
                    "shifts": [],
                    "attach_modes": [],
                    "field_replace": False,
                    "status": "NEEDS_REVIEW",
                    "note": "待人工复核",
                }
            ]

            updated = build_assembly.apply_gap_plan(plan, gap_plan_path)

        # 未通过质检的 AI 填写产物不得进入组装，且必须显式提示"AI 填写未完成"
        self.assertEqual(updated[0]["status"], "UNMATCHED")
        self.assertEqual(updated[0]["paths"], [])
        self.assertIn("AI 填写未完成", updated[0]["note"])
        self.assertEqual(updated[0]["gap_plan_item_id"], "GAP-0058")



    def test_bid_assembler_gap_plan_blocks_partially_reviewed_multi_fill_task_item(self) -> None:
        """R10-B07-02：多 fillTask 只复核一个，S7 不得因存在任一可用产物而放行整项。"""
        build_assembly = load_assembler_script("build_assembly")

        with tempfile.TemporaryDirectory() as tmp:
            gap_plan_path = Path(tmp) / "gap_plan.json"
            gap_plan_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "GAP-0058",
                                "number": "附表A.1",
                                "title": "投标机型总方案信息表",
                                "fillTasks": [
                                    {"id": "FILL-0058-A", "status": "completed"},
                                    {"id": "FILL-0058-B", "status": "pending"},
                                ],
                                "matchedMaterials": [],
                                "resolvedArtifacts": [
                                    {
                                        "source": "ai_fill",
                                        "fillTaskId": "FILL-0058-A",
                                        "path": "/tmp/机组参数表_AI填写.docx",
                                        "s7Ready": True,
                                        "qualityGate": "human_confirmed",
                                    }
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plan = [
                {
                    "chapter_no_flat": "附表A.1",
                    "chapter_no": "",
                    "title": "投标机型总方案信息表",
                    "paths": [],
                    "shifts": [],
                    "attach_modes": [],
                    "field_replace": False,
                    "status": "NEEDS_REVIEW",
                    "note": "待人工复核",
                }
            ]

            updated = build_assembly.apply_gap_plan(plan, gap_plan_path)

        # 塔筒参数表仍 pending：整项阻断并显式提示，不能只合并已复核的机组参数表。
        self.assertEqual(updated[0]["status"], "UNMATCHED")
        self.assertEqual(updated[0]["paths"], [])
        self.assertIn("AI 填写未完成", updated[0]["note"])
        self.assertEqual(updated[0]["gap_plan_item_id"], "GAP-0058")



    def test_bid_assembler_gap_plan_merges_multi_fill_task_item_after_all_reviewed(self) -> None:
        """R10-B07-02：所有 fillTask 完成且产物均放行后，S7 正常合并全部产物。"""
        build_assembly = load_assembler_script("build_assembly")

        with tempfile.TemporaryDirectory() as tmp:
            gap_plan_path = Path(tmp) / "gap_plan.json"
            gap_plan_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "GAP-0058",
                                "number": "附表A.1",
                                "title": "投标机型总方案信息表",
                                "fillTasks": [
                                    {"id": "FILL-0058-A", "status": "completed"},
                                    {"id": "FILL-0058-B", "status": "completed"},
                                ],
                                "matchedMaterials": [],
                                "resolvedArtifacts": [
                                    {
                                        "source": "ai_fill",
                                        "fillTaskId": "FILL-0058-A",
                                        "path": "/tmp/机组参数表_AI填写.docx",
                                        "s7Ready": True,
                                        "qualityGate": "human_confirmed",
                                    },
                                    {
                                        "source": "ai_fill",
                                        "fillTaskId": "FILL-0058-B",
                                        "path": "/tmp/塔筒参数表_AI填写.docx",
                                        "s7Ready": True,
                                        "qualityGate": "human_confirmed",
                                    },
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plan = [
                {
                    "chapter_no_flat": "附表A.1",
                    "chapter_no": "",
                    "title": "投标机型总方案信息表",
                    "paths": [],
                    "shifts": [],
                    "attach_modes": [],
                    "field_replace": False,
                    "status": "NEEDS_REVIEW",
                    "note": "待人工复核",
                }
            ]

            updated = build_assembly.apply_gap_plan(plan, gap_plan_path)

        self.assertEqual(updated[0]["status"], "MATCHED")
        self.assertEqual(
            updated[0]["paths"],
            ["/tmp/机组参数表_AI填写.docx", "/tmp/塔筒参数表_AI填写.docx"],
        )
        self.assertEqual(updated[0]["gap_plan_item_id"], "GAP-0058")



    def test_bid_assembler_gap_plan_manual_artifact_replaces_pending_fill_task(self) -> None:
        """R10-B07-02：人工上传/选材产物按决策终审可替代填写任务，不被 pending 任务误阻断。"""
        build_assembly = load_assembler_script("build_assembly")

        with tempfile.TemporaryDirectory() as tmp:
            gap_plan_path = Path(tmp) / "gap_plan.json"
            gap_plan_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "GAP-0058",
                                "number": "附表A.1",
                                "title": "投标机型总方案信息表",
                                "fillTasks": [{"id": "FILL-0058-A", "status": "pending"}],
                                "matchedMaterials": [],
                                "resolvedArtifacts": [
                                    {
                                        "source": "manual_upload",
                                        "path": "/tmp/人工上传_总方案信息表.docx",
                                        "s7Ready": True,
                                    }
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plan = [
                {
                    "chapter_no_flat": "附表A.1",
                    "chapter_no": "",
                    "title": "投标机型总方案信息表",
                    "paths": [],
                    "shifts": [],
                    "attach_modes": [],
                    "field_replace": False,
                    "status": "NEEDS_REVIEW",
                    "note": "待人工复核",
                }
            ]

            updated = build_assembly.apply_gap_plan(plan, gap_plan_path)

        self.assertEqual(updated[0]["status"], "MATCHED")
        self.assertEqual(updated[0]["paths"], ["/tmp/人工上传_总方案信息表.docx"])
        self.assertEqual(updated[0]["gap_plan_item_id"], "GAP-0058")



    def test_bid_assembler_gap_plan_preserves_structural_items(self) -> None:
        build_assembly = load_assembler_script("build_assembly")

        with tempfile.TemporaryDirectory() as tmp:
            gap_plan_path = Path(tmp) / "gap_plan.json"
            gap_plan_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "GAP-0137",
                                "number": "技术附表B",
                                "title": "供货范围、消耗品及安装调试人员计划",
                                "status": "structural",
                                "gapReason": "结构性目录项，不直接要求素材。",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plan = [
                {
                    "toc_idx": 136,
                    "level": 1,
                    "chapter_no_flat": "",
                    "chapter_no": "",
                    "title": "技术附表B 供货范围、消耗品及安装调试人员计划",
                    "paths": [],
                    "shifts": [],
                    "attach_modes": [],
                    "field_replace": False,
                    "status": "NEEDS_REVIEW",
                    "note": "招标/模板新增章节，需人工补素材",
                }
            ]

            updated = build_assembly.apply_gap_plan(plan, gap_plan_path)

        self.assertEqual(updated[0]["status"], "STRUCTURAL")
        self.assertEqual(updated[0]["paths"], [])
        self.assertEqual(updated[0]["gap_plan_item_id"], "GAP-0137")
