from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from toc_skill_helpers import (
    TocSkillScriptTestBase,
    json_load,
    load_outline_script,
    submit_outline_changes,
)


class TocSkillScriptTests(TocSkillScriptTestBase):

    def test_bid_outline_cli_runtime_compose_gate_cannot_be_disabled_by_manifest(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "toc.json"
            manifest_path = root / "s2_input.json"
            manifest = {
                "workDir": str(root),
                "outputFile": str(output),
                "requireComposedOutline": False,
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "template_structure.json").write_text(
                json.dumps(
                    {
                        "schema_version": "template-structure.v1",
                        "items": [{"number": "第1章", "title": "技术方案", "level": 1}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            submit_outline_changes(outline_runner, manifest, manifest_path, [])
            output.write_text(
                json.dumps(
                    {
                        "schema_version": "technical-outline.v1",
                        "nodes": [
                            {
                                "number": "第1章",
                                "title": "技术方案",
                                "suggestion_action": "必要",
                                "suggestion_reason": "",
                                "children": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(
                sys,
                "argv",
                ["run_from_manifest.py", "--require-compose", "finalize", str(manifest_path)],
            ), self.assertRaisesRegex(SystemExit, "尚未执行 s2outline compose"):
                outline_runner.main()



    def test_bid_outline_compose_keeps_all_explicitly_retained_template_level_three(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "toc.json"
            manifest_path = root / "s2_input.json"
            manifest = {"workDir": str(root), "outputFile": str(output)}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "template_structure.json").write_text(
                json.dumps(
                    {
                        "schema_version": "template-structure.v1",
                        "items": [
                            {"number": "第1章", "title": "技术方案", "level": 1},
                            {"number": "1.1", "title": "总体设计", "level": 2},
                            {"number": "1.1.1", "title": "设计原则", "level": 3},
                            {"number": "1.1.2", "title": "设计边界", "level": 3},
                            {"number": "1.2", "title": "供货方案", "level": 2},
                            {"number": "1.2.1", "title": "供货范围", "level": 3},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            submit_outline_changes(outline_runner, manifest, manifest_path, [])
            result = outline_runner.compose_manifest(manifest, manifest_path)
            outline = json_load(output)

        first_root = outline["nodes"][0]
        self.assertEqual(
            [child["title"] for parent in first_root["children"] for child in parent["children"]],
            ["设计原则", "设计边界", "供货范围"],
        )
        self.assertEqual(result["summary"]["templateLevel3"]["templateCount"], 3)
        self.assertEqual(result["summary"]["templateLevel3"]["retainedCount"], 3)
        self.assertEqual(result["summary"]["templateLevel3"]["unexplainedMissingCount"], 0)



    def test_bid_outline_compose_preserves_realistic_6_48_150_template_structure(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "s2_input.json"
            output = root / "toc.json"
            manifest = {"workDir": str(root), "outputFile": str(output)}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            items = []
            expected_children_by_parent: dict[str, list[tuple[str, str]]] = {}
            parent_index = 0
            for chapter_index in range(1, 7):
                items.append(
                    {
                        "number": f"第{chapter_index}章",
                        "title": f"技术方案{chapter_index}",
                        "level": 1,
                    }
                )
                for section_index in range(1, 9):
                    parent_index += 1
                    parent_number = f"{chapter_index}.{section_index}"
                    items.append(
                        {
                            "number": parent_number,
                            "title": f"二级专题{parent_index}",
                            "level": 2,
                        }
                    )
                    child_count = 5 if parent_index <= 14 else 4 if parent_index <= 34 else 0
                    expected_children_by_parent[parent_number] = []
                    for child_index in range(1, child_count + 1):
                        child_number = f"{parent_number}.{child_index}"
                        child_title = f"三级专题{parent_index}-{child_index}"
                        items.append(
                            {
                                "number": child_number,
                                "title": child_title,
                                "level": 3,
                            }
                        )
                        expected_children_by_parent[parent_number].append(
                            (child_number, child_title)
                        )
            (root / "template_structure.json").write_text(
                json.dumps(
                    {"schema_version": "template-structure.v1", "items": items},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            submit_outline_changes(outline_runner, manifest, manifest_path, [])
            result = outline_runner.compose_manifest(manifest, manifest_path)
            outline = json_load(output)

        parents = [parent for root_node in outline["nodes"] for parent in root_node["children"]]
        coverage = result["summary"]["templateLevel3"]
        coverage_by_parent = {item["number"]: item for item in coverage["parents"]}
        self.assertEqual(len(outline["nodes"]), 6)
        self.assertEqual(len(parents), 48)
        self.assertEqual(sum(len(parent["children"]) for parent in parents), 150)
        self.assertEqual(coverage["templateCount"], 150)
        self.assertEqual(coverage["retainedCount"], 150)
        self.assertEqual(coverage["unexplainedMissingCount"], 0)
        self.assertEqual(len(coverage["parents"]), 48)
        for parent in parents:
            expected_children = expected_children_by_parent[parent["number"]]
            self.assertEqual(
                [(child["number"], child["title"]) for child in parent["children"]],
                expected_children,
            )
            self.assertTrue(
                all(
                    child["number"].startswith(f'{parent["number"]}.')
                    for child in parent["children"]
                )
            )
            self.assertEqual(
                coverage_by_parent[parent["number"]]["finalCount"],
                len(expected_children),
            )



    def test_bid_outline_compose_applies_explicit_collapse_and_addition(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "toc.json"
            manifest_path = root / "s2_input.json"
            manifest = {"workDir": str(root), "outputFile": str(output)}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "template_structure.json").write_text(
                json.dumps(
                    {
                        "schema_version": "template-structure.v1",
                        "items": [
                            {"number": "第1章", "title": "技术方案", "level": 1},
                            {"number": "1.1", "title": "总体设计", "level": 2},
                            {"number": "1.1.1", "title": "设计原则", "level": 3},
                            {"number": "1.1.2", "title": "设计边界", "level": 3},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions = {
                "schema_version": "technical-outline-decisions.v1",
                "changes": [
                    {
                        "operation": "collapse",
                        "target_id": "TPL-0003",
                        "reason": "内容由总体设计统一承载，不需要独立分工和审核。",
                    },
                    {
                        "operation": "add",
                        "node_id": "ADD-0001",
                        "parent_id": "TPL-0002",
                        "after_id": "TPL-0004",
                        "number": "1.1.3",
                        "title": "专项计算报告",
                        "suggestion_action": "建议增加",
                        "suggestion_reason": "招标明确要求独立提交专项计算报告。",
                    },
                ],
            }

            submit_outline_changes(outline_runner, manifest, manifest_path, decisions["changes"])
            result = outline_runner.compose_manifest(manifest, manifest_path)
            outline = json_load(output)

        children = outline["nodes"][0]["children"][0]["children"]
        self.assertEqual([child["title"] for child in children], ["设计边界", "专项计算报告"])
        self.assertEqual(result["summary"]["templateLevel3"]["collapsedCount"], 1)
        self.assertEqual(result["summary"]["templateLevel3"]["addedCount"], 1)
        self.assertEqual(result["summary"]["templateLevel3"]["unexplainedMissingCount"], 0)



    def test_bid_outline_finalize_reports_missing_template_level_three_without_blocking(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "toc.json"
            manifest_path = root / "s2_input.json"
            manifest = {"workDir": str(root), "outputFile": str(output)}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "template_structure.json").write_text(
                json.dumps(
                    {
                        "schema_version": "template-structure.v1",
                        "items": [
                            {"number": "第1章", "title": "技术方案", "level": 1},
                            {"number": "1.1", "title": "总体设计", "level": 2},
                            {"number": "1.1.1", "title": "设计原则", "level": 3},
                            {"number": "1.1.2", "title": "设计边界", "level": 3},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output.write_text(
                json.dumps(
                    {
                        "schema_version": "technical-outline.v1",
                        "nodes": [
                            {
                                "number": "第1章",
                                "title": "技术方案",
                                "suggestion_action": "必要",
                                "suggestion_reason": "",
                                "children": [
                                    {
                                        "number": "1.1",
                                        "title": "总体设计",
                                        "suggestion_action": "必要",
                                        "suggestion_reason": "",
                                        "children": [
                                            {
                                                "number": "1.1.1",
                                                "title": "设计原则",
                                                "suggestion_action": "必要",
                                                "suggestion_reason": "",
                                                "children": [],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = outline_runner.finalize_manifest(manifest, manifest_path)

        coverage = result["summary"]["templateLevel3"]
        self.assertEqual(coverage["templateCount"], 2)
        self.assertEqual(coverage["retainedCount"], 1)
        self.assertEqual(coverage["unexplainedMissingCount"], 1)
        self.assertEqual(coverage["parentsWithUnexplainedMissing"], 1)



    def test_bid_outline_finalize_requires_unchanged_composed_output_when_enabled(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "toc.json"
            manifest_path = root / "s2_input.json"
            manifest = {
                "workDir": str(root),
                "outputFile": str(output),
                "requireComposedOutline": True,
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "template_structure.json").write_text(
                json.dumps(
                    {
                        "schema_version": "template-structure.v1",
                        "items": [{"number": "第1章", "title": "技术方案", "level": 1}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            submit_outline_changes(outline_runner, manifest, manifest_path, [])
            outline_runner.compose_manifest(manifest, manifest_path)
            result = outline_runner.finalize_manifest(manifest, manifest_path)
            payload = json_load(output)
            payload["nodes"][0]["title"] = "被临时脚本改写的目录"
            output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "compose 后被修改"):
                outline_runner.finalize_manifest(manifest, manifest_path)

        self.assertEqual(result["summary"]["workflowStage"], "finalized")



    def test_bid_outline_compose_keeps_suggested_delete_and_tracks_level_three_move(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "toc.json"
            manifest_path = root / "s2_input.json"
            manifest = {"workDir": str(root), "outputFile": str(output)}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "template_structure.json").write_text(
                json.dumps(
                    {
                        "schema_version": "template-structure.v1",
                        "items": [
                            {"number": "第1章", "title": "技术方案", "level": 1},
                            {"number": "1.1", "title": "总体设计", "level": 2},
                            {"number": "1.1.1", "title": "原设计专题", "level": 3},
                            {"number": "1.2", "title": "专项方案", "level": 2},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions = {
                "schema_version": "technical-outline-decisions.v1",
                "changes": [
                    {
                        "operation": "suggest_delete",
                        "target_id": "TPL-0002",
                        "reason": "当前项目供货边界不包含该总体设计工作。",
                    },
                    {
                        "operation": "update",
                        "target_id": "TPL-0003",
                        "parent_id": "TPL-0004",
                        "number": "1.2.1",
                        "title": "调整后的设计专题",
                        "reason": "该专题应归入专项方案并独立编制。",
                    },
                ],
            }

            submit_outline_changes(outline_runner, manifest, manifest_path, decisions["changes"])
            result = outline_runner.compose_manifest(manifest, manifest_path)
            outline = json_load(output)

        first_parent, second_parent = outline["nodes"][0]["children"]
        self.assertEqual(first_parent["suggestion_action"], "建议删除")
        self.assertEqual(first_parent["suggestion_reason"], "当前项目供货边界不包含该总体设计工作。")
        self.assertEqual(first_parent["children"], [])
        self.assertEqual(second_parent["children"][0]["number"], "1.2.1")
        self.assertEqual(second_parent["children"][0]["title"], "调整后的设计专题")
        parents = {
            item["parentId"]: item for item in result["summary"]["templateLevel3"]["parents"]
        }
        self.assertEqual(parents["TPL-0002"]["retainedCount"], 0)
        self.assertEqual(parents["TPL-0002"]["movedOutCount"], 1)
        self.assertEqual(parents["TPL-0004"]["movedInCount"], 1)
        self.assertEqual(parents["TPL-0004"]["finalCount"], 1)



    def test_bid_outline_level_three_report_includes_added_parent(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "s2_input.json"
            manifest = {"workDir": str(root), "outputFile": str(root / "toc.json")}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "template_structure.json").write_text(
                json.dumps(
                    {
                        "schema_version": "template-structure.v1",
                        "items": [{"number": "第1章", "title": "技术方案", "level": 1}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            changes = [
                {
                    "operation": "add",
                    "node_id": "ADD-L2",
                    "parent_id": "TPL-0001",
                    "number": "1.1",
                    "title": "新增专项",
                    "suggestion_action": "建议增加",
                    "suggestion_reason": "招标要求新增专项。",
                },
                {
                    "operation": "add",
                    "node_id": "ADD-L3",
                    "parent_id": "ADD-L2",
                    "number": "1.1.1",
                    "title": "新增专项报告",
                    "suggestion_action": "建议增加",
                    "suggestion_reason": "招标要求独立提交报告。",
                },
            ]

            submit_outline_changes(outline_runner, manifest, manifest_path, changes)
            result = outline_runner.compose_manifest(manifest, manifest_path)

        parents = {
            item["parentId"]: item for item in result["summary"]["templateLevel3"]["parents"]
        }
        self.assertEqual(parents["ADD-L2"]["templateCount"], 0)
        self.assertEqual(parents["ADD-L2"]["addedCount"], 1)
        self.assertEqual(parents["ADD-L2"]["finalCount"], 1)



    def test_bid_outline_level_three_report_distinguishes_cross_level_move_from_addition(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "s2_input.json"
            manifest = {"workDir": str(root), "outputFile": str(root / "toc.json")}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "template_structure.json").write_text(
                json.dumps(
                    {
                        "schema_version": "template-structure.v1",
                        "items": [
                            {"number": "第1章", "title": "技术方案", "level": 1},
                            {"number": "1.1", "title": "总体设计", "level": 2},
                            {"number": "1.1.1", "title": "原三级专题", "level": 3},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            changes = [
                {
                    "operation": "update",
                    "target_id": "TPL-0003",
                    "parent_id": None,
                    "number": "第2章",
                    "reason": "该专题调整为独立根章节。",
                },
                {
                    "operation": "add",
                    "node_id": "ADD-L3",
                    "parent_id": "TPL-0002",
                    "number": "1.1.2",
                    "title": "新增三级报告",
                    "suggestion_action": "建议增加",
                    "suggestion_reason": "招标要求独立提交。",
                },
            ]

            submit_outline_changes(outline_runner, manifest, manifest_path, changes)
            result = outline_runner.compose_manifest(manifest, manifest_path)

        coverage = result["summary"]["templateLevel3"]
        self.assertEqual(coverage["templateCount"], 1)
        self.assertEqual(coverage["outputCount"], 1)
        self.assertEqual(coverage["retainedCount"], 0)
        self.assertEqual(coverage["movedOutOfLevel3Count"], 1)
        self.assertEqual(coverage["addedCount"], 1)
        self.assertEqual(coverage["unexplainedMissingCount"], 0)



    def test_bid_outline_level_three_report_counts_template_node_moved_into_level_three(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "s2_input.json"
            manifest = {"workDir": str(root), "outputFile": str(root / "toc.json")}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "template_structure.json").write_text(
                json.dumps(
                    {
                        "schema_version": "template-structure.v1",
                        "items": [
                            {"number": "第1章", "title": "技术方案", "level": 1},
                            {"number": "1.1", "title": "原二级叶节点", "level": 2},
                            {"number": "1.2", "title": "目标二级节点", "level": 2},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            changes = [
                {
                    "operation": "update",
                    "target_id": "TPL-0002",
                    "parent_id": "TPL-0003",
                    "number": "1.2.1",
                    "reason": "调整为目标二级节点下的独立三级专题。",
                }
            ]

            submit_outline_changes(outline_runner, manifest, manifest_path, changes)
            result = outline_runner.compose_manifest(manifest, manifest_path)

        coverage = result["summary"]["templateLevel3"]
        parents = {item["parentId"]: item for item in coverage["parents"]}
        self.assertEqual(coverage["outputCount"], 1)
        self.assertEqual(coverage["retainedCount"], 0)
        self.assertEqual(coverage["addedCount"], 0)
        self.assertEqual(coverage["movedIntoLevel3Count"], 1)
        self.assertEqual(parents["TPL-0003"]["movedInCount"], 1)
        self.assertEqual(parents["TPL-0003"]["finalCount"], 1)



    def test_bid_outline_finalize_rejects_missing_or_stale_compose_receipt(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "toc.json"
            manifest_path = root / "s2_input.json"
            manifest = {
                "workDir": str(root),
                "outputFile": str(output),
                "requireComposedOutline": True,
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "template_structure.json").write_text(
                json.dumps(
                    {
                        "schema_version": "template-structure.v1",
                        "items": [{"number": "第1章", "title": "技术方案", "level": 1}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output.write_text(
                json.dumps(
                    {
                        "schema_version": "technical-outline.v1",
                        "nodes": [
                            {
                                "number": "第1章",
                                "title": "技术方案",
                                "suggestion_action": "必要",
                                "suggestion_reason": "",
                                "children": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            submit_outline_changes(outline_runner, manifest, manifest_path, [])
            with self.assertRaisesRegex(SystemExit, "尚未执行 s2outline compose"):
                outline_runner.finalize_manifest(manifest, manifest_path)

            outline_runner.compose_manifest(manifest, manifest_path)
            decisions_path = root / "outline_authoring_decisions.json"
            changed_decisions = json_load(decisions_path)
            changed_decisions["changes"] = [
                {
                    "operation": "add",
                    "node_id": "ADD-STALE",
                    "parent_id": None,
                    "number": "第2章",
                    "title": "新增章节",
                    "suggestion_action": "建议增加",
                    "suggestion_reason": "用于验证决策变更后回执失效。",
                }
            ]
            decisions_path.write_text(json.dumps(changed_decisions, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "decisions.*compose 后被修改"):
                outline_runner.finalize_manifest(manifest, manifest_path)



    def test_bid_outline_finalize_rejects_output_not_reproducible_from_decisions(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "toc.json"
            manifest_path = root / "s2_input.json"
            manifest = {
                "workDir": str(root),
                "outputFile": str(output),
                "requireComposedOutline": True,
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            structure = {
                "schema_version": "template-structure.v1",
                "items": [{"number": "第1章", "title": "技术方案", "level": 1}],
            }
            (root / "template_structure.json").write_text(
                json.dumps(structure, ensure_ascii=False), encoding="utf-8"
            )
            fingerprint = outline_runner.outline_composer.annotate_template_structure(structure)[
                "input_fingerprint"
            ]
            outline_runner.submit_outline_decisions(
                manifest,
                manifest_path,
                {
                    "schema_version": "technical-outline-decisions.v1",
                    "input_fingerprint": fingerprint,
                    "template_decisions": [
                        {"target_id": "TPL-0001", "decision": "retain"}
                    ],
                    "changes": [],
                },
            )
            outline_runner.compose_manifest(manifest, manifest_path)
            payload = json_load(output)
            payload["nodes"][0]["title"] = "硬编码改写结果"
            output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            report_path = root / "outline_compose_report.json"
            report = json_load(report_path)
            report["outputSha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
            report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "与 decisions 合成结果不一致"):
                outline_runner.finalize_manifest(manifest, manifest_path)
