from __future__ import annotations

import json
import tempfile
from pathlib import Path

from toc_skill_helpers import (
    TocSkillScriptTestBase,
    json_load,
    load_outline_script,
    write_decision_context_fixture,
)


class TocSkillScriptTests(TocSkillScriptTestBase):

    def test_bid_outline_appendix_candidates_keep_missing_source_status(self) -> None:
        review_workflow = load_outline_script("review_workflow")

        items = review_workflow.decision_appendix_items_from_inventory(
            {
                "schema_version": "tender-appendix-inventory.v1",
                "items": [
                    {"file_id": "TEN-1", "number": "技术附表E", "title": "技术要求", "following_table_count": 0},
                    {"file_id": "TEN-1", "number": "E.3", "title": "偏差表", "following_table_count": 1},
                    {"file_id": "TEN-1", "number": "E.4", "title": "承诺表", "following_table_count": 0},
                ],
            }
        )

        self.assertEqual([item["number"] for item in items], ["E.3", "E.4"])
        self.assertEqual([item["source_status"] for item in items], ["present", "missing"])



    def test_bid_outline_added_chapter_keeps_technical_appendix_last(self) -> None:
        outline_composer = load_outline_script("outline_composer")
        structure = {
            "schema_version": "template-structure.v1",
            "items": [{"number": "第1章", "title": "总体方案", "level": 1}],
        }
        decisions = {
            "schema_version": "technical-outline-decisions.v1",
            "input_fingerprint": outline_composer.annotate_template_structure(structure)[
                "input_fingerprint"
            ],
            "template_decisions": [
                {"target_id": "TPL-0001", "decision": "retain", "reason": "承接整体技术论证。"}
            ],
            "changes": [
                {
                    "operation": "add",
                    "node_id": "ADD-APPENDIX",
                    "parent_id": None,
                    "number": "附录",
                    "title": "技术附表",
                    "suggestion_action": "建议增加",
                    "suggestion_reason": "招标文件包含独立附表。",
                },
                {
                    "operation": "add",
                    "node_id": "ADD-CHAPTER",
                    "parent_id": None,
                    "number": "第2章",
                    "title": "专项试验方案",
                    "suggestion_action": "建议增加",
                    "suggestion_reason": "全局查漏发现的独立成章要求。",
                },
            ],
        }

        outline, _ = outline_composer.build_composition(structure, decisions)

        self.assertEqual(
            [node["title"] for node in outline["nodes"]],
            ["总体方案", "专项试验方案", "技术附表"],
        )



    def test_bid_outline_decision_batch_rejects_appendix_additions_outside_queue(self) -> None:
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
            (root / "tender_appendix_inventory.json").write_text(
                json.dumps(
                    {
                        "schema_version": "tender-appendix-inventory.v1",
                        "items": [
                            {
                                "file_id": "TEN-1",
                                "file_name": "招标文件.docx",
                                "number": "附表A.1",
                                "title": "投标机型总方案信息表",
                                "raw_text": "附表A.1 投标机型总方案信息表",
                                "following_table_count": 1,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            batch = outline_runner.dispatch_command(
                "decision-next", manifest, manifest_path, []
            )
            with self.assertRaisesRegex(
                SystemExit, "技术附表必须通过 appendix-decision-batch 决策"
            ):
                outline_runner.dispatch_command(
                    "decision-batch",
                    manifest,
                    manifest_path,
                    [
                        json.dumps(
                            {
                                "batch_token": batch["batch_token"],
                                "items": [
                                    {
                                        "target_id": batch["items"][0]["target_id"],
                                        "decision": "retain",
                                    }
                                ],
                                "additions": [
                                    {
                                        "node_id": "ADD-TECH-APPENDIX",
                                        "parent_id": None,
                                        "number": "第2章",
                                        "title": "技术附表",
                                        "reason": "招标包含实际技术附表。",
                                    },
                                    {
                                        "node_id": "ADD-APPENDIX-A1",
                                        "parent_id": "ADD-TECH-APPENDIX",
                                        "appendix_id": "APP-0001",
                                        "reason": "招标结构化清单中的实际表单。",
                                    },
                                ],
                            },
                            ensure_ascii=False,
                        )
                    ],
                )
            state = json_load(root / "outline_decision_state.json")

        self.assertEqual(state["additions"], [])
        self.assertEqual(state["appendix_decisions"], {})
        self.assertEqual(state["active_batch"]["target_ids"], ["TPL-0001"])



    def test_bid_outline_appendix_batches_require_explicit_include_or_exclude(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, manifest_path = write_decision_context_fixture(root, heading_count=0)
            template_batch = outline_runner.dispatch_command(
                "decision-next", manifest, manifest_path, []
            )
            with self.assertRaisesRegex(SystemExit, "先完成模板"):
                outline_runner.dispatch_command("appendix-next", manifest, manifest_path, [])
            outline_runner.dispatch_command(
                "decision-batch",
                manifest,
                manifest_path,
                [
                    json.dumps(
                        {
                            "batch_token": template_batch["batch_token"],
                            "items": [
                                {
                                    "target_id": template_batch["items"][0]["target_id"],
                                    "decision": "retain",
                                }
                            ],
                            "additions": [],
                        }
                    )
                ],
            )
            inventory_path = root / "tender_appendix_inventory.json"
            inventory_path.write_text(
                json.dumps(
                    {
                        "schema_version": "tender-appendix-inventory.v1",
                        "items": [
                            {
                                "file_id": "TEN-1",
                                "number": f"Appendix A.{index}",
                                "title": f"Controlled form {index}",
                                "following_table_count": 0 if index == 2 else 1,
                            }
                            for index in range(1, 4)
                        ],
                    }
                ),
                encoding="utf-8",
            )

            for invalid_max_items in (0, 41):
                with self.subTest(max_items=invalid_max_items):
                    with self.assertRaisesRegex(SystemExit, "between 1 and 40"):
                        outline_runner.dispatch_command(
                            "appendix-next",
                            manifest,
                            manifest_path,
                            ["--max-items", str(invalid_max_items)],
                        )

            for invalid_args in (
                ["--unknown"],
                ["--max-items"],
                ["--max-items", "2", "extra"],
            ):
                with self.subTest(invalid_args=invalid_args):
                    with self.assertRaisesRegex(SystemExit, "appendix-next usage"):
                        outline_runner.dispatch_command(
                            "appendix-next", manifest, manifest_path, invalid_args
                        )

            batch = outline_runner.dispatch_command(
                "appendix-next", manifest, manifest_path, ["--max-items", "2"]
            )
            self.assertEqual(
                [item["appendix_id"] for item in batch["items"]],
                ["APP-0001", "APP-0002"],
            )
            self.assertEqual(batch["decided_count"], 0)
            self.assertEqual(batch["remaining_count"], 3)
            self.assertFalse(batch["complete"])
            self.assertEqual(
                batch["submission_contract"],
                {
                    "items_must_match_batch": True,
                    "items_must_keep_returned_order": True,
                    "exclude_fields": ["appendix_id", "decision", "reason"],
                    "include_fields": [
                        "appendix_id",
                        "decision",
                        "node_id",
                        "parent_id",
                        "reason",
                    ],
                    "include_parent_id": "必须引用本批 root_addition.node_id 或已有唯一技术附表根节点",
                    "reason_required": "include 与 exclude 都必须提交 reason",
                    "missing_rule": "source_status=missing 必须 exclude；只有 source_status=present 才自主判断 include 或 exclude",
                    "root_addition": {
                        "required_when": "首次 include 且尚无唯一的技术附表根节点",
                        "omit_when": "根节点已建立后的所有后续批次禁止再提交 root_addition",
                        "fields": ["node_id", "reason"],
                        "generated_fields": {
                            "parent_id": None,
                            "number": "附录",
                            "title": "技术附表",
                        },
                    },
                },
            )

            with self.assertRaisesRegex(
                SystemExit, "appendix-decision-batch requires exactly one JSON payload"
            ):
                outline_runner.dispatch_command(
                    "appendix-decision-batch",
                    manifest,
                    manifest_path,
                    [
                        json.dumps(
                            {
                                "batch_token": batch["batch_token"],
                                "items": [
                                    {
                                        "appendix_id": item["appendix_id"],
                                        "decision": "exclude",
                                        "reason": "Not required.",
                                    }
                                    for item in batch["items"]
                                ],
                            }
                        ),
                        "extra",
                    ],
                )

            invalid_item_lists = [
                [
                    {"appendix_id": "APP-0001", "decision": "exclude", "reason": "no"},
                    {"appendix_id": "APP-0001", "decision": "exclude", "reason": "no"},
                ],
                [
                    {"appendix_id": "APP-0001", "decision": "exclude", "reason": "no"},
                    {"appendix_id": "APP-9999", "decision": "exclude", "reason": "no"},
                ],
                [
                    {"appendix_id": "APP-0002", "decision": "exclude", "reason": "no"},
                    {"appendix_id": "APP-0001", "decision": "exclude", "reason": "no"},
                ],
                [
                    {"appendix_id": "APP-0001", "decision": "exclude", "reason": "no"},
                ],
            ]
            for invalid_items in invalid_item_lists:
                with self.subTest(invalid_items=invalid_items):
                    with self.assertRaisesRegex(SystemExit, "exactly match"):
                        outline_runner.dispatch_command(
                            "appendix-decision-batch",
                            manifest,
                            manifest_path,
                            [json.dumps({"batch_token": batch["batch_token"], "items": invalid_items})],
                        )

            with self.assertRaisesRegex(SystemExit, "source_status=missing.*must be exclude"):
                outline_runner.dispatch_command(
                    "appendix-decision-batch",
                    manifest,
                    manifest_path,
                    [
                        json.dumps(
                            {
                                "batch_token": batch["batch_token"],
                                "items": [
                                    {
                                        "appendix_id": "APP-0001",
                                        "decision": "exclude",
                                        "reason": "Not required.",
                                    },
                                    {
                                        "appendix_id": "APP-0002",
                                        "decision": "include",
                                        "node_id": "ADD-APP-2",
                                        "parent_id": "ADD-APP-ROOT",
                                        "reason": "Include it.",
                                    },
                                ],
                            }
                        )
                    ],
                )
            state_after_missing = json_load(root / "outline_decision_state.json")
            self.assertEqual(state_after_missing["appendix_decisions"], {})
            self.assertEqual(
                state_after_missing["active_appendix_batch"]["appendix_ids"],
                ["APP-0001", "APP-0002"],
            )

            outline_runner.dispatch_command(
                "appendix-decision-batch",
                manifest,
                manifest_path,
                [
                    json.dumps(
                        {
                            "batch_token": batch["batch_token"],
                            "items": [
                                {
                                    "appendix_id": item["appendix_id"],
                                    "decision": "exclude",
                                    "reason": "Not required by this tender.",
                                }
                                for item in batch["items"]
                            ],
                        }
                    )
                ],
            )
            second = outline_runner.dispatch_command(
                "appendix-next", manifest, manifest_path, ["--max-items", "2"]
            )
            self.assertEqual(
                [item["appendix_id"] for item in second["items"]], ["APP-0003"]
            )

            inventory = json_load(inventory_path)
            inventory["items"][2]["title"] = "Changed after token issuance"
            inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "inventory.*changed"):
                outline_runner.dispatch_command("appendix-next", manifest, manifest_path, [])
            with self.assertRaisesRegex(SystemExit, "inventory.*changed"):
                outline_runner.dispatch_command(
                    "appendix-decision-batch",
                    manifest,
                    manifest_path,
                    [
                        json.dumps(
                            {
                                "batch_token": second["batch_token"],
                                "items": [
                                    {
                                        "appendix_id": "APP-0003",
                                        "decision": "exclude",
                                        "reason": "Not required.",
                                    }
                                ],
                            }
                        )
                    ],
                )
            with self.assertRaisesRegex(SystemExit, "inventory.*changed"):
                outline_runner.dispatch_command("decisions", manifest, manifest_path, [])



    def test_bid_outline_appendix_decision_progress_is_read_only(self) -> None:
        decision_workflow = load_outline_script("run_from_manifest").decision_workflow
        structure = {
            "schema_version": "template-structure.v1",
            "items": [{"number": "1", "title": "Technical proposal", "level": 1}],
        }
        inventory = [
            {
                "appendix_id": "APP-0001",
                "file_id": "TEN-1",
                "number": "Appendix B.1",
                "title": "Guaranteed data sheet",
                "raw_text": "Appendix B.1Guaranteed data sheet",
                "following_table_count": 1,
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = decision_workflow.next_decision_batch(root, structure)
            decision_workflow.submit_decision_batch(
                root,
                structure,
                {
                    "batch_token": template["batch_token"],
                    "items": [
                        {
                            "target_id": template["items"][0]["target_id"],
                            "decision": "retain",
                            "reason": "历史模板专家经验仍适用。",
                        }
                    ],
                    "additions": [],
                },
            )
            pending = decision_workflow.appendix_decision_progress(
                root, structure, inventory
            )
            state_before_batch = json_load(root / "outline_decision_state.json")
            batch = decision_workflow.next_appendix_batch(root, structure, inventory)
            in_flight = decision_workflow.appendix_decision_progress(
                root, structure, inventory
            )
            decision_workflow.submit_appendix_batch(
                root,
                structure,
                {
                    "batch_token": batch["batch_token"],
                    "items": [
                        {
                            "appendix_id": "APP-0001",
                            "decision": "include",
                            "node_id": "ADD-B1",
                            "parent_id": "ADD-TECH-APPENDIX",
                            "reason": "Tender requires the completed form.",
                        }
                    ],
                    "root_addition": {
                        "node_id": "ADD-TECH-APPENDIX",
                        "reason": "Tender contains controlled appendices.",
                    },
                },
                inventory,
            )
            done = decision_workflow.appendix_decision_progress(
                root, structure, inventory
            )

        self.assertEqual(
            pending,
            {
                "decidedCount": 0,
                "remainingCount": 1,
                "activeBatch": False,
                "complete": False,
            },
        )
        # 进度查询不得发放批次令牌或改动状态
        self.assertEqual(
            state_before_batch["active_appendix_batch"],
            {"token": "", "appendix_ids": []},
        )
        self.assertFalse(in_flight["complete"])
        self.assertTrue(in_flight["activeBatch"])
        self.assertTrue(done["complete"])
        self.assertEqual(done["decidedCount"], 1)
        self.assertEqual(done["remainingCount"], 0)



    def test_bid_outline_appendix_cli_rejects_non_string_json_fields_atomically(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, manifest_path = write_decision_context_fixture(
                root, heading_count=0
            )
            (root / "tender_appendix_inventory.json").write_text(
                json.dumps(
                    {
                        "schema_version": "tender-appendix-inventory.v1",
                        "items": [
                            {
                                "appendix_id": "7",
                                "file_id": "TEN-1",
                                "number": "Appendix T.1",
                                "title": "Typed form",
                                "following_table_count": 1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            template = outline_runner.dispatch_command(
                "decision-next", manifest, manifest_path, []
            )
            outline_runner.dispatch_command(
                "decision-batch",
                manifest,
                manifest_path,
                [
                    json.dumps(
                        {
                            "batch_token": template["batch_token"],
                            "items": [
                                {
                                    "target_id": template["items"][0]["target_id"],
                                    "decision": "retain",
                                }
                            ],
                            "additions": [],
                        }
                    )
                ],
            )
            batch = outline_runner.dispatch_command(
                "appendix-next", manifest, manifest_path, []
            )
            state_path = root / "outline_decision_state.json"
            original_state = state_path.read_text(encoding="utf-8")
            valid_root = {
                "node_id": "ADD-TECH-APPENDIX",
                "parent_id": None,
                "number": "第7章",
                "title": "技术附表",
                "reason": "Required root.",
            }
            valid_include = {
                "appendix_id": batch["items"][0]["appendix_id"],
                "decision": "include",
                "node_id": "ADD-APP-0001",
                "parent_id": "ADD-TECH-APPENDIX",
                "reason": "Required form.",
            }

            invalid_payloads: list[tuple[str, dict]] = []
            for field in ("node_id", "number", "title", "reason"):
                for value in ([], {"unexpected": True}, 7):
                    root_addition = {**valid_root, field: value}
                    item = dict(valid_include)
                    if field == "node_id":
                        item["parent_id"] = str(value)
                    invalid_payloads.append(
                        (
                            rf"root_addition\.{field} must be a string",
                            {
                                "batch_token": batch["batch_token"],
                                "root_addition": root_addition,
                                "items": [item],
                            },
                        )
                    )
            for value in ("TPL-0001", {"unexpected": True}):
                invalid_payloads.append(
                    (
                        r"root_addition\.parent_id must be null",
                        {
                            "batch_token": batch["batch_token"],
                            "root_addition": {**valid_root, "parent_id": value},
                            "items": [valid_include],
                        },
                    )
                )

            invalid_item_cases = [
                ("appendix_id", 7, r"items\[0\]\.appendix_id must be a string"),
                ("decision", ["include"], r"items\[0\]\.decision must be a string"),
                ("node_id", {"unexpected": True}, r"items\[0\]\.node_id must be a string"),
                ("reason", [], r"items\[0\]\.reason must be a string"),
            ]
            for field, value, message in invalid_item_cases:
                invalid_payloads.append(
                    (
                        message,
                        {
                            "batch_token": batch["batch_token"],
                            "root_addition": valid_root,
                            "items": [{**valid_include, field: value}],
                        },
                    )
                )
            invalid_payloads.append(
                (
                    r"items\[0\]\.parent_id must be a string",
                    {
                        "batch_token": batch["batch_token"],
                        "root_addition": {**valid_root, "node_id": "7"},
                        "items": [{**valid_include, "parent_id": 7}],
                    },
                )
            )
            for field, value, message in (
                ("appendix_id", 7, r"items\[0\]\.appendix_id must be a string"),
                ("decision", ["exclude"], r"items\[0\]\.decision must be a string"),
                ("reason", {"unexpected": True}, r"items\[0\]\.reason must be a string"),
            ):
                invalid_payloads.append(
                    (
                        message,
                        {
                            "batch_token": batch["batch_token"],
                            "items": [
                                {
                                    "appendix_id": batch["items"][0]["appendix_id"],
                                    "decision": "exclude",
                                    "reason": "Not required.",
                                    field: value,
                                }
                            ],
                        },
                    )
                )

            for message, payload in invalid_payloads:
                with self.subTest(message=message, payload=payload):
                    state_path.write_text(original_state, encoding="utf-8")
                    with self.assertRaisesRegex(SystemExit, message):
                        outline_runner.dispatch_command(
                            "appendix-decision-batch",
                            manifest,
                            manifest_path,
                            [json.dumps(payload, ensure_ascii=False)],
                        )
                    self.assertEqual(
                        state_path.read_text(encoding="utf-8"), original_state
                    )



    def test_bid_outline_appendix_later_first_include_creates_root(self) -> None:
        decision_workflow = load_outline_script("run_from_manifest").decision_workflow
        structure = {
            "schema_version": "template-structure.v1",
            "items": [{"number": "1", "title": "Technical proposal", "level": 1}],
        }
        inventory = [
            {
                "appendix_id": f"APP-{index:04d}",
                "file_id": "TEN-1",
                "number": f"Appendix L.{index}",
                "title": f"Later form {index}",
                "following_table_count": 1,
            }
            for index in range(1, 3)
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = decision_workflow.next_decision_batch(
                root, structure
            )
            decision_workflow.submit_decision_batch(
                root,
                structure,
                {
                    "batch_token": template["batch_token"],
                    "items": [
                        {
                            "target_id": template["items"][0]["target_id"],
                            "decision": "retain",
                        }
                    ],
                },
            )
            first = decision_workflow.next_appendix_batch(
                root, structure, inventory, max_items=1
            )
            decision_workflow.submit_appendix_batch(
                root,
                structure,
                {
                    "batch_token": first["batch_token"],
                    "items": [
                        {
                            "appendix_id": "APP-0001",
                            "decision": "exclude",
                            "reason": "Not required.",
                        }
                    ],
                },
                inventory,
            )
            self.assertEqual(
                json_load(root / "outline_decision_state.json")["additions"], []
            )

            second = decision_workflow.next_appendix_batch(
                root, structure, inventory, max_items=1
            )
            decision_workflow.submit_appendix_batch(
                root,
                structure,
                {
                    "batch_token": second["batch_token"],
                    "root_addition": {
                        "node_id": "ADD-TECH-APPENDIX",
                        "parent_id": None,
                        "number": "第7章",
                        "title": "技术附表",
                        "reason": "Later batch first include.",
                    },
                    "items": [
                        {
                            "appendix_id": "APP-0002",
                            "decision": "include",
                            "node_id": "ADD-APP-0002",
                            "parent_id": "ADD-TECH-APPENDIX",
                            "reason": "Required later form.",
                        }
                    ],
                },
                inventory,
            )
            finalized = decision_workflow.finalize_decisions(
                root, structure, appendix_items=inventory
            )
            decisions = json_load(Path(finalized["decisionsFile"]))
            outline, _ = decision_workflow.outline_composer.build_composition(
                structure, decisions
            )

        self.assertEqual(outline["nodes"][-1]["title"], "技术附表")
        self.assertEqual(
            [item["title"] for item in outline["nodes"][-1]["children"]],
            ["Later form 2"],
        )



    def test_bid_outline_decisions_reject_unjudged_appendix_candidates(self) -> None:
        decision_workflow = load_outline_script("decision_workflow")
        structure = {
            "schema_version": "template-structure.v1",
            "items": [{"number": "1", "title": "Technical proposal", "level": 1}],
        }
        inventory = [
            {
                "appendix_id": f"APP-{index:04d}",
                "file_id": "TEN-1",
                "number": f"Appendix C.{index}",
                "title": f"Form {index}",
                "following_table_count": 1,
            }
            for index in range(1, 22)
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = decision_workflow.next_decision_batch(
                root, structure
            )
            decision_workflow.submit_decision_batch(
                root,
                structure,
                {
                    "batch_token": template["batch_token"],
                    "items": [
                        {
                            "target_id": template["items"][0]["target_id"],
                            "decision": "retain",
                        }
                    ],
                },
            )
            with self.assertRaises(SystemExit) as raised:
                decision_workflow.finalize_decisions(
                    root, structure, appendix_items=inventory
                )

        message = str(raised.exception)
        self.assertIn("APP-0001", message)
        self.assertIn("APP-0020", message)
        self.assertNotIn("APP-0021", message)



    def test_bid_outline_appendix_submit_validates_complete_composition_atomically(self) -> None:
        decision_workflow = load_outline_script("run_from_manifest").decision_workflow
        structure = {
            "schema_version": "template-structure.v1",
            "items": [{"number": "1", "title": "Technical proposal", "level": 1}],
        }
        inventory = [
            {
                "appendix_id": "APP-0001",
                "file_id": "TEN-1",
                "number": "Appendix E.1",
                "title": "Validated form",
                "following_table_count": 1,
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = decision_workflow.next_decision_batch(
                root, structure
            )
            decision_workflow.submit_decision_batch(
                root,
                structure,
                {
                    "batch_token": template["batch_token"],
                    "items": [
                        {
                            "target_id": template["items"][0]["target_id"],
                            "decision": "retain",
                        }
                    ],
                    "additions": [
                        {
                            "node_id": "ADD-TECH-APPENDIX",
                            "parent_id": None,
                            "number": "2",
                            "title": "技术附表",
                            "reason": "Controlled appendix root.",
                        },
                        {
                            "node_id": "ADD-INVALID-EXISTING",
                            "parent_id": None,
                            "number": "",
                            "title": "Invalid existing change",
                            "reason": "Empty number must be rejected by the builder.",
                        },
                    ],
                },
            )
            batch = decision_workflow.next_appendix_batch(root, structure, inventory)

            def include_payload(parent_id: str) -> dict:
                return {
                    "batch_token": batch["batch_token"],
                    "items": [
                        {
                            "appendix_id": "APP-0001",
                            "decision": "include",
                            "node_id": "ADD-APPENDIX-E1",
                            "parent_id": parent_id,
                            "reason": "Required controlled form.",
                        }
                    ],
                }

            corrected_parent_state = json_load(root / "outline_decision_state.json")
            with self.assertRaisesRegex(SystemExit, "changes\\[1\\]\\.number"):
                decision_workflow.submit_appendix_batch(
                    root,
                    structure,
                    include_payload("ADD-TECH-APPENDIX"),
                    inventory,
                )
            self.assertEqual(
                json_load(root / "outline_decision_state.json"), corrected_parent_state
            )

            corrected_parent_state["additions"][1]["number"] = "3"
            (root / "outline_decision_state.json").write_text(
                json.dumps(corrected_parent_state, ensure_ascii=False), encoding="utf-8"
            )
            decision_workflow.submit_appendix_batch(
                root,
                structure,
                include_payload("ADD-TECH-APPENDIX"),
                inventory,
            )
            decision_workflow.finalize_decisions(
                root, structure, appendix_items=inventory
            )
            final_state = json_load(root / "outline_decision_state.json")

        self.assertEqual(final_state["active_appendix_batch"]["appendix_ids"], [])
        self.assertEqual(final_state["appendix_decisions"]["APP-0001"]["decision"], "include")
