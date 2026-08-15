from __future__ import annotations

import json
import tempfile
from pathlib import Path

from toc_skill_helpers import (
    TocSkillScriptTestBase,
    json_load,
    load_outline_script,
)


class TocSkillScriptTests(TocSkillScriptTestBase):

    def test_bid_outline_appendix_predecision_materializes_after_template_merge(self) -> None:
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
                "raw_text": "Appendix B.1 Guaranteed data sheet",
                "following_table_count": 1,
                "source_status": "present",
            },
            {
                "appendix_id": "APP-0002",
                "file_id": "TEN-1",
                "number": "Appendix B.2",
                "title": "Instructions only",
                "raw_text": "Appendix B.2 Instructions only",
                "following_table_count": 0,
                "source_status": "missing",
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_dir = root / "main"
            predecision_dir = root / "appendix"
            main_dir.mkdir()
            predecision_dir.mkdir()

            batch = decision_workflow.next_appendix_predecision_batch(
                predecision_dir,
                structure,
                inventory,
            )
            self.assertEqual(
                batch["submission_contract"]["include_fields"],
                ["appendix_id", "decision", "reason"],
            )
            decision_workflow.submit_appendix_predecision_batch(
                predecision_dir,
                structure,
                {
                    "batch_token": batch["batch_token"],
                    "items": [
                        {
                            "appendix_id": "APP-0001",
                            "decision": "include",
                            "reason": "Tender requires the completed data sheet.",
                        },
                        {
                            "appendix_id": "APP-0002",
                            "decision": "exclude",
                            "reason": "No independent table is present.",
                        },
                    ],
                },
                inventory,
            )

            with self.assertRaisesRegex(SystemExit, "模板逐项判断"):
                decision_workflow.materialize_appendix_predecisions(
                    main_dir,
                    predecision_dir,
                    structure,
                    inventory,
                )

            template = decision_workflow.next_decision_batch(main_dir, structure)
            decision_workflow.submit_decision_batch(
                main_dir,
                structure,
                {
                    "batch_token": template["batch_token"],
                    "items": [
                        {
                            "target_id": template["items"][0]["target_id"],
                            "decision": "retain",
                            "reason": "Historical structure remains applicable.",
                        }
                    ],
                    "additions": [],
                },
            )
            result = decision_workflow.materialize_appendix_predecisions(
                main_dir,
                predecision_dir,
                structure,
                inventory,
            )
            state = json_load(main_dir / "outline_decision_state.json")

        self.assertTrue(result["complete"])
        self.assertEqual(result["included_count"], 1)
        self.assertEqual(result["excluded_count"], 1)
        self.assertEqual(
            state["appendix_decisions"]["APP-0001"]["decision"], "include"
        )
        self.assertEqual(
            state["appendix_decisions"]["APP-0002"]["decision"], "exclude"
        )
        appendix_roots = [
            item
            for item in state["additions"]
            if item.get("parent_id") is None and item.get("title") == "技术附表"
        ]
        self.assertEqual(len(appendix_roots), 1)
        self.assertEqual(
            [item["parent_id"] for item in state["additions"] if item.get("parent_id")],
            [appendix_roots[0]["node_id"]],
        )



    def test_bid_outline_appendix_batch_copies_inventory_metadata_for_include(self) -> None:
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
            {
                "appendix_id": "APP-0002",
                "file_id": "TEN-1",
                "number": "Appendix B.2",
                "title": "Reference only",
                "following_table_count": 0,
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = decision_workflow.next_decision_batch(
                root, structure
            )
            initial_state = json_load(root / "outline_decision_state.json")
            with self.assertRaisesRegex(SystemExit, "node_id is missing or duplicate"):
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
                                "node_id": "TPL-0001",
                                "parent_id": None,
                                "number": "2",
                                "title": "技术附表",
                                "reason": "Conflicts with the template node ID.",
                            }
                        ],
                    },
                )
            self.assertEqual(json_load(root / "outline_decision_state.json"), initial_state)

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
                            "reason": "Tender contains controlled appendices.",
                        }
                    ],
                },
            )
            with self.assertRaisesRegex(SystemExit, "duplicate"):
                decision_workflow.next_appendix_batch(
                    root, structure, [inventory[0], inventory[0]]
                )
            batch = decision_workflow.next_appendix_batch(root, structure, inventory)

            invalid_payloads = [
                [
                    {"appendix_id": "APP-0001", "decision": "include", "parent_id": "ROOT", "reason": "Required."},
                    {"appendix_id": "APP-0002", "decision": "exclude", "reason": "No."},
                ],
                [
                    {"appendix_id": "APP-0001", "decision": "include", "node_id": "ADD-B1", "reason": "Required."},
                    {"appendix_id": "APP-0002", "decision": "exclude", "reason": "No."},
                ],
                [
                    {"appendix_id": "APP-0001", "decision": "include", "node_id": "ADD-B1", "parent_id": "ROOT"},
                    {"appendix_id": "APP-0002", "decision": "exclude", "reason": "No."},
                ],
                [
                    {"appendix_id": "APP-0001", "decision": "include", "node_id": "ADD-B1", "parent_id": "ADD-TECH-APPENDIX", "reason": "Required."},
                    {"appendix_id": "APP-0002", "decision": "exclude"},
                ],
            ]
            for invalid_items in invalid_payloads:
                with self.subTest(invalid_items=invalid_items):
                    with self.assertRaisesRegex(SystemExit, "required"):
                        decision_workflow.submit_appendix_batch(
                            root,
                            structure,
                            {"batch_token": batch["batch_token"], "items": invalid_items},
                            inventory,
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
                        },
                        {
                            "appendix_id": "APP-0002",
                            "decision": "exclude",
                            "reason": "Heading only; no independent form.",
                        },
                    ],
                },
                inventory,
            )
            state = json_load(root / "outline_decision_state.json")
            finalized = decision_workflow.finalize_decisions(
                root, structure, appendix_items=inventory
            )

        self.assertEqual(state["schema_version"], decision_workflow.STATE_SCHEMA)
        self.assertEqual(state["appendix_decisions"]["APP-0001"]["decision"], "include")
        self.assertEqual(state["appendix_decisions"]["APP-0001"]["reason"], "Tender requires the completed form.")
        self.assertEqual(state["appendix_decisions"]["APP-0002"]["decision"], "exclude")
        self.assertEqual(len(state["additions"]), 2)
        self.assertEqual(state["additions"][1]["number"], "Appendix B.1")
        self.assertEqual(state["additions"][1]["title"], "Guaranteed data sheet")
        self.assertEqual(
            state["additions"][1]["tender_basis"]["search_text"],
            "Appendix B.1Guaranteed data sheet",
        )
        self.assertTrue(finalized["decisionsFile"])



    def test_bid_outline_appendix_include_requires_unique_valid_root_parent_atomically(self) -> None:
        decision_workflow = load_outline_script("run_from_manifest").decision_workflow
        structure = {
            "schema_version": "template-structure.v1",
            "items": [{"number": "1", "title": "Technical proposal", "level": 1}],
        }
        inventory = [
            {
                "appendix_id": f"APP-{index:04d}",
                "file_id": "TEN-1",
                "number": f"Appendix D.{index}",
                "title": f"Controlled form {index}",
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
                    "additions": [
                        {
                            "node_id": "ADD-TECH-APPENDIX",
                            "parent_id": None,
                            "number": "2",
                            "title": "技术附表",
                            "reason": "Valid root.",
                        },
                        {
                            "node_id": "ADD-NESTED-APPENDIX",
                            "parent_id": "TPL-0001",
                            "number": "1.1",
                            "title": "技术附表",
                            "reason": "Nested candidate.",
                        },
                        {
                            "node_id": "ADD-WRONG-TITLE",
                            "parent_id": None,
                            "number": "3",
                            "title": "技术附件",
                            "reason": "Wrong title candidate.",
                        },
                    ],
                },
            )
            batch = decision_workflow.next_appendix_batch(root, structure, inventory)
            original_state = json_load(root / "outline_decision_state.json")

            def include_payload(node_ids: list[str], parent_id: str) -> dict:
                return {
                    "batch_token": batch["batch_token"],
                    "items": [
                        {
                            "appendix_id": item["appendix_id"],
                            "decision": "include",
                            "node_id": node_ids[index],
                            "parent_id": parent_id,
                            "reason": "Required controlled form.",
                        }
                        for index, item in enumerate(batch["items"])
                    ],
                }

            invalid_root_states = []
            deleted_root_state = json.loads(json.dumps(original_state))
            deleted_root_state["additions"].append(
                {
                    "operation": "suggest_delete",
                    "target_id": "ADD-TECH-APPENDIX",
                }
            )
            invalid_root_states.append(("deleted root", deleted_root_state))
            duplicate_root_state = json.loads(json.dumps(original_state))
            duplicate_root_state["additions"].append(
                {
                    "operation": "add",
                    "node_id": "ADD-SECOND-TECH-APPENDIX",
                    "parent_id": None,
                    "number": "4",
                    "title": "技术附表",
                    "suggestion_action": "建议增加",
                    "suggestion_reason": "Ambiguous root.",
                }
            )
            invalid_root_states.append(("duplicate roots", duplicate_root_state))
            for label, invalid_state in invalid_root_states:
                with self.subTest(label=label):
                    (root / "outline_decision_state.json").write_text(
                        json.dumps(invalid_state, ensure_ascii=False), encoding="utf-8"
                    )
                    with self.assertRaisesRegex(SystemExit, "parent_id|root_addition"):
                        decision_workflow.submit_appendix_batch(
                            root,
                            structure,
                            include_payload(
                                ["ADD-VALID-1", "ADD-VALID-2"],
                                "ADD-TECH-APPENDIX",
                            ),
                            inventory,
                        )
                    self.assertEqual(
                        json_load(root / "outline_decision_state.json"), invalid_state
                    )
            (root / "outline_decision_state.json").write_text(
                json.dumps(original_state, ensure_ascii=False), encoding="utf-8"
            )

            invalid_cases = [
                ("template node", ["TPL-0001", "ADD-VALID-2"], "ADD-TECH-APPENDIX"),
                ("existing addition", ["ADD-TECH-APPENDIX", "ADD-VALID-2"], "ADD-TECH-APPENDIX"),
                ("same batch", ["ADD-DUPLICATE", "ADD-DUPLICATE"], "ADD-TECH-APPENDIX"),
                ("missing parent", ["ADD-VALID-1", "ADD-VALID-2"], "ADD-MISSING"),
                ("nested parent", ["ADD-VALID-1", "ADD-VALID-2"], "ADD-NESTED-APPENDIX"),
                ("wrong title", ["ADD-VALID-1", "ADD-VALID-2"], "ADD-WRONG-TITLE"),
            ]
            for label, node_ids, parent_id in invalid_cases:
                with self.subTest(label=label):
                    with self.assertRaisesRegex(SystemExit, "node_id|parent_id"):
                        decision_workflow.submit_appendix_batch(
                            root,
                            structure,
                            include_payload(node_ids, parent_id),
                            inventory,
                        )
                    self.assertEqual(
                        json_load(root / "outline_decision_state.json"), original_state
                    )

            decision_workflow.submit_appendix_batch(
                root,
                structure,
                {
                    "batch_token": batch["batch_token"],
                    "items": [
                        {
                            "appendix_id": item["appendix_id"],
                            "decision": "include",
                            "node_id": f"ADD-VALID-{index}",
                            "parent_id": "ADD-TECH-APPENDIX",
                            "reason": "Required controlled form.",
                        }
                        for index, item in enumerate(batch["items"], start=1)
                    ],
                },
                inventory,
            )
            final_state = json_load(root / "outline_decision_state.json")
            decision_workflow.finalize_decisions(
                root, structure, appendix_items=inventory
            )

        self.assertEqual(final_state["active_appendix_batch"]["appendix_ids"], [])
        self.assertEqual(set(final_state["appendix_decisions"]), {"APP-0001", "APP-0002"})



    def test_bid_outline_appendix_first_include_creates_root_and_later_batch_reuses_it(self) -> None:
        decision_workflow = load_outline_script("run_from_manifest").decision_workflow
        structure = {
            "schema_version": "template-structure.v1",
            "items": [{"number": "1", "title": "Technical proposal", "level": 1}],
        }
        inventory = [
            {
                "appendix_id": f"APP-{index:04d}",
                "file_id": "TEN-1",
                "number": f"Appendix R.{index}",
                "title": f"Controlled form {index}",
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
                    "root_addition": {
                        "node_id": "ADD-TECH-APPENDIX",
                        "parent_id": None,
                        "number": "第7章",
                        "title": "技术附表",
                        "reason": "Tender contains controlled appendices.",
                    },
                    "items": [
                        {
                            "appendix_id": "APP-0001",
                            "decision": "include",
                            "node_id": "ADD-APP-0001",
                            "parent_id": "ADD-TECH-APPENDIX",
                            "reason": "Include first form.",
                        }
                    ],
                },
                inventory,
            )
            first_state = json_load(root / "outline_decision_state.json")
            second = decision_workflow.next_appendix_batch(
                root, structure, inventory, max_items=1
            )
            second_state = json_load(root / "outline_decision_state.json")

            with self.assertRaisesRegex(SystemExit, "root_addition"):
                decision_workflow.submit_appendix_batch(
                    root,
                    structure,
                    {
                        "batch_token": second["batch_token"],
                        "root_addition": {
                            "node_id": "ADD-SECOND-ROOT",
                            "parent_id": None,
                            "number": "第8章",
                            "title": "技术附表",
                            "reason": "Duplicate root.",
                        },
                        "items": [
                            {
                                "appendix_id": "APP-0002",
                                "decision": "include",
                                "node_id": "ADD-APP-0002",
                                "parent_id": "ADD-SECOND-ROOT",
                                "reason": "Include second form.",
                            }
                        ],
                    },
                    inventory,
                )
            self.assertEqual(
                json_load(root / "outline_decision_state.json"), second_state
            )

            decision_workflow.submit_appendix_batch(
                root,
                structure,
                {
                    "batch_token": second["batch_token"],
                    "items": [
                        {
                            "appendix_id": "APP-0002",
                            "decision": "include",
                            "node_id": "ADD-APP-0002",
                            "parent_id": "ADD-TECH-APPENDIX",
                            "reason": "Include second form.",
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
            validation = decision_workflow.validate_finalized_decisions(
                root,
                structure,
                decisions,
                workflow_binding={},
                appendix_items=inventory,
                include_appendix_decisions=True,
            )

        self.assertEqual(
            first_state["additions"][0],
            {
                "operation": "add",
                "node_id": "ADD-TECH-APPENDIX",
                "parent_id": None,
                "number": "附录",
                "title": "技术附表",
                "suggestion_action": "建议增加",
                "suggestion_reason": "Tender contains controlled appendices.",
            },
        )
        self.assertEqual(
            outline["nodes"][-1],
            {
                "number": "附录",
                "title": "技术附表",
                "suggestion_action": "建议增加",
                "suggestion_reason": "Tender contains controlled appendices.",
                "children": [
                    {
                        "number": "Appendix R.1",
                        "title": "Controlled form 1",
                        "suggestion_action": "建议增加",
                        "suggestion_reason": "Include first form.",
                        "tender_basis": {
                            "file_id": "TEN-1",
                            "search_text": "Appendix R.1 Controlled form 1",
                        },
                        "children": [],
                    },
                    {
                        "number": "Appendix R.2",
                        "title": "Controlled form 2",
                        "suggestion_action": "建议增加",
                        "suggestion_reason": "Include second form.",
                        "tender_basis": {
                            "file_id": "TEN-1",
                            "search_text": "Appendix R.2 Controlled form 2",
                        },
                        "children": [],
                    },
                ],
            },
        )
        self.assertEqual(
            [item["decision"] for item in validation["appendixDecisions"]],
            ["include", "include"],
        )



    def test_bid_outline_appendix_root_addition_validation_is_atomic(self) -> None:
        decision_workflow = load_outline_script("run_from_manifest").decision_workflow
        structure = {
            "schema_version": "template-structure.v1",
            "items": [{"number": "1", "title": "Technical proposal", "level": 1}],
        }
        inventory = [
            {
                "appendix_id": "APP-0001",
                "file_id": "TEN-1",
                "number": "Appendix V.1",
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
                            "node_id": "ADD-EXISTING",
                            "parent_id": None,
                            "number": "2",
                            "title": "Other section",
                            "reason": "Existing non-appendix addition.",
                        }
                    ],
                },
            )
            batch = decision_workflow.next_appendix_batch(root, structure, inventory)
            original_state = json_load(root / "outline_decision_state.json")

            include_item = {
                "appendix_id": "APP-0001",
                "decision": "include",
                "node_id": "ADD-APP-0001",
                "parent_id": "ADD-TECH-APPENDIX",
                "reason": "Required form.",
            }
            valid_root = {
                "node_id": "ADD-TECH-APPENDIX",
                "parent_id": None,
                "number": "第7章",
                "title": "技术附表",
                "reason": "Required appendix root.",
            }
            invalid_payloads = [
                ("root_addition", {"batch_token": batch["batch_token"], "items": [include_item]}),
                (
                    "reason",
                    {
                        "batch_token": batch["batch_token"],
                        "root_addition": {key: value for key, value in valid_root.items() if key != "reason"},
                        "items": [include_item],
                    },
                ),
                (
                    "template node",
                    {
                        "batch_token": batch["batch_token"],
                        "root_addition": {**valid_root, "node_id": "TPL-0001"},
                        "items": [include_item],
                    },
                ),
                (
                    "existing addition",
                    {
                        "batch_token": batch["batch_token"],
                        "root_addition": {**valid_root, "node_id": "ADD-EXISTING"},
                        "items": [include_item],
                    },
                ),
                (
                    "parent_id",
                    {
                        "batch_token": batch["batch_token"],
                        "root_addition": {**valid_root, "parent_id": "TPL-0001"},
                        "items": [include_item],
                    },
                ),
                (
                    "number",
                    {
                        "batch_token": batch["batch_token"],
                        "root_addition": {**valid_root, "number": ""},
                        "items": [include_item],
                    },
                ),
                (
                    "title",
                    {
                        "batch_token": batch["batch_token"],
                        "root_addition": {**valid_root, "title": "技术附件"},
                        "items": [include_item],
                    },
                ),
                (
                    "parent_id",
                    {
                        "batch_token": batch["batch_token"],
                        "root_addition": valid_root,
                        "items": [{**include_item, "parent_id": "ADD-WRONG-ROOT"}],
                    },
                ),
                (
                    "node_id",
                    {
                        "batch_token": batch["batch_token"],
                        "root_addition": valid_root,
                        "items": [{**include_item, "node_id": "ADD-TECH-APPENDIX"}],
                    },
                ),
                (
                    "root_addition",
                    {
                        "batch_token": batch["batch_token"],
                        "root_addition": valid_root,
                        "items": [
                            {
                                "appendix_id": "APP-0001",
                                "decision": "exclude",
                                "reason": "Not required.",
                            }
                        ],
                    },
                ),
            ]
            for message, payload in invalid_payloads:
                with self.subTest(message=message):
                    with self.assertRaisesRegex(SystemExit, message):
                        decision_workflow.submit_appendix_batch(
                            root, structure, payload, inventory
                        )
                    self.assertEqual(
                        json_load(root / "outline_decision_state.json"), original_state
                    )

            decision_workflow.submit_appendix_batch(
                root,
                structure,
                {
                    "batch_token": batch["batch_token"],
                    "root_addition": {
                        "node_id": "ADD-TECH-APPENDIX",
                        "reason": "Required appendix root.",
                    },
                    "items": [include_item],
                },
                inventory,
            )
            final_state = json_load(root / "outline_decision_state.json")

        self.assertEqual(final_state["active_appendix_batch"]["appendix_ids"], [])
        self.assertEqual(len(final_state["additions"]), 3)
        appendix_root = next(
            item for item in final_state["additions"] if item.get("node_id") == "ADD-TECH-APPENDIX"
        )
        self.assertEqual(appendix_root["parent_id"], None)
        self.assertEqual(appendix_root["number"], "附录")
        self.assertEqual(appendix_root["title"], "技术附表")



    def test_bid_outline_appendix_all_exclude_finishes_without_root(self) -> None:
        decision_workflow = load_outline_script("run_from_manifest").decision_workflow
        structure = {
            "schema_version": "template-structure.v1",
            "items": [{"number": "1", "title": "Technical proposal", "level": 1}],
        }
        inventory = [
            {
                "appendix_id": f"APP-{index:04d}",
                "file_id": "TEN-1",
                "number": f"Appendix X.{index}",
                "title": f"Excluded form {index}",
                "following_table_count": 1,
            }
            for index in range(1, 65)
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

            while True:
                batch = decision_workflow.next_appendix_batch(
                    root, structure, inventory
                )
                if batch["complete"]:
                    break
                decision_workflow.submit_appendix_batch(
                    root,
                    structure,
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
                    },
                    inventory,
                )

            state = json_load(root / "outline_decision_state.json")
            finalized = decision_workflow.finalize_decisions(
                root, structure, appendix_items=inventory
            )
            decisions = json_load(Path(finalized["decisionsFile"]))
            outline, _ = decision_workflow.outline_composer.build_composition(
                structure, decisions
            )
            validation = decision_workflow.validate_finalized_decisions(
                root,
                structure,
                decisions,
                workflow_binding={},
                appendix_items=inventory,
                include_appendix_decisions=True,
            )

        self.assertEqual(state["additions"], [])
        self.assertEqual(decisions["changes"], [])
        self.assertNotIn("技术附表", json.dumps(outline, ensure_ascii=False))
        self.assertEqual(len(validation["appendixDecisions"]), 64)
        self.assertTrue(
            all(item["decision"] == "exclude" for item in validation["appendixDecisions"])
        )
