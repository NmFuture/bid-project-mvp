from __future__ import annotations

import asyncio
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from app.services import technical_material_index as tmi
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.material_folder_scope import material_tier_root_path
from app.services.technical_material_paths import (
    canonical_technical_material_child_name,
    ensure_technical_material_new_child_path,
    ensure_technical_material_write_path,
)
from app.services.peripheral import PeripheralError


def _tree() -> dict:
    """模拟 raw_tree() 输出：技术标(1) -> 三档(2) -> 动态子目录(3)。"""
    return {
        "tree": [
            {
                "name": "技术标",
                "path": "技术标",
                "children": [
                    {
                        "name": "通用素材",
                        "path": "技术标/通用素材",
                        "children": [
                            {"name": "公司介绍", "path": "技术标/通用素材/公司介绍", "children": []},
                        ],
                    },
                    {
                        "name": "客户素材",
                        "path": "技术标/客户素材",
                        "children": [
                            {"name": "华能集团", "path": "技术标/客户素材/华能集团", "children": []},
                        ],
                    },
                    {
                        "name": "项目素材",
                        "path": "技术标/项目素材",
                        "children": [
                            {"name": "MAT-HN-001", "path": "技术标/项目素材/MAT-HN-001", "children": []},
                        ],
                    },
                ],
            }
        ],
        "updatedAt": "2026-06-18 14:30:00",
    }


def _files() -> list[dict]:
    return [
        {"id": "RAW-0001", "name": "公司简介.pdf", "folderPath": "技术标/通用素材/公司介绍", "ext": "pdf", "cleanStatus": "cleaned"},
        # 深层文件应归并到它的 3 级祖先 技术标/通用素材/公司介绍
        {"id": "RAW-0002", "name": "深层.docx", "folderPath": "技术标/通用素材/公司介绍/2024/Q1", "ext": "docx", "cleanStatus": "pending"},
        {"id": "RAW-0003", "name": "客户授权.pdf", "folderPath": "技术标/客户素材/华能集团", "ext": "pdf", "cleanStatus": "cleaned"},
        # 2 级目录直接挂的文件（无 3 级祖先）应被忽略，不计入任何 3 级目录
        {"id": "RAW-0009", "name": "散落.pdf", "folderPath": "技术标/通用素材", "ext": "pdf", "cleanStatus": "pending"},
    ]


class BuildPayloadTests(unittest.TestCase):
    def test_resolve_tier_real_world_and_legacy_names(self) -> None:
        # 实际库的 2 级目录名（标准文件/客户定制/项目定制）。
        self.assertEqual(tmi._resolve_tier("标准文件"), "standard")
        self.assertEqual(tmi._resolve_tier("客户定制"), "customer")
        self.assertEqual(tmi._resolve_tier("项目定制"), "project")
        # 建库模板默认名（通用素材/客户素材/项目素材）也应归一。
        self.assertEqual(tmi._resolve_tier("通用素材"), "standard")
        self.assertEqual(tmi._resolve_tier("客户素材"), "customer")
        self.assertEqual(tmi._resolve_tier("项目素材"), "project")
        # 未知名兜底为 standard（技术标 2 级目录非客户/项目即标准）。
        self.assertEqual(tmi._resolve_tier("其他随便什么"), "standard")

    def test_material_folder_key_excludes_unknown_second_level_folder(self) -> None:
        self.assertEqual(
            tmi._material_folder_key("技术标/国电投"),
            "",
        )
        self.assertEqual(
            tmi._material_folder_key("技术标/国电投/子目录"),
            "",
        )
        self.assertEqual(
            tmi._material_folder_key("技术标/标准文件/EW6.25/专题"),
            "技术标/标准文件/EW6.25",
        )

    def test_real_world_folder_names_backfill_identity(self) -> None:
        # 用实际库的命名（标准文件/客户定制/项目定制）验证 tier 与身份回填。
        tree = {
            "tree": [
                {
                    "name": "技术标",
                    "path": "技术标",
                    "children": [
                        {
                            "name": "客户定制",
                            "path": "技术标/客户定制",
                            "children": [
                                {"name": "华能", "path": "技术标/客户定制/华能", "children": []},
                            ],
                        },
                        {
                            "name": "项目定制",
                            "path": "技术标/项目定制",
                            "children": [
                                {"name": "邢台50MW", "path": "技术标/项目定制/邢台50MW", "children": []},
                            ],
                        },
                    ],
                }
            ]
        }
        payload = tmi._build_payload(tree, [])
        customer = next(t for t in payload["tiers"] if t["name"] == "客户定制")
        self.assertEqual(customer["tier"], "customer")
        self.assertEqual(customer["folders"][0]["customerName"], "华能")
        project = next(t for t in payload["tiers"] if t["name"] == "项目定制")
        self.assertEqual(project["tier"], "project")
        self.assertEqual(project["folders"][0]["projectId"], "邢台50MW")

    def test_third_level_path_merges_deep_to_ancestor(self) -> None:
        self.assertEqual(
            tmi._third_level_path("技术标/通用素材/公司介绍/2024/Q1"),
            "技术标/通用素材/公司介绍",
        )

    def test_third_level_path_returns_empty_above_third_level(self) -> None:
        self.assertEqual(tmi._third_level_path("技术标/通用素材"), "")
        self.assertEqual(tmi._third_level_path("技术标"), "")
        self.assertEqual(tmi._third_level_path("商务标/通用素材/x"), "")

    def test_build_payload_structure_and_stats(self) -> None:
        payload = tmi._build_payload(_tree(), _files())

        self.assertEqual(payload["bidType"], "技术标")
        self.assertEqual(payload["schemaVersion"], tmi.SCHEMA_VERSION)
        # 3 个 3 级目录、3 个有效文件（散落.pdf 被忽略）
        self.assertEqual(payload["stats"]["tierCount"], 3)
        self.assertEqual(payload["stats"]["thirdLevelFolderCount"], 3)
        self.assertEqual(payload["stats"]["fileCount"], 3)

        tiers = {tier["name"]: tier for tier in payload["tiers"]}
        self.assertEqual(set(tiers), {"通用素材", "客户素材", "项目素材"})
        self.assertEqual(tiers["通用素材"]["tier"], "standard")
        self.assertEqual(tiers["客户素材"]["tier"], "customer")
        self.assertEqual(tiers["项目素材"]["tier"], "project")

    def test_files_merged_into_correct_third_level_folder(self) -> None:
        payload = tmi._build_payload(_tree(), _files())
        general = next(t for t in payload["tiers"] if t["name"] == "通用素材")
        folder = general["folders"][0]
        self.assertEqual(folder["path"], "技术标/通用素材/公司介绍")
        # 直接文件 + 深层文件都归到这个 3 级目录
        self.assertEqual(folder["fileCount"], 2)
        self.assertEqual(general["fileCount"], 2)
        ids = {f["id"] for f in folder["files"]}
        self.assertEqual(ids, {"RAW-0001", "RAW-0002"})
        deep = next(f for f in folder["files"] if f["id"] == "RAW-0002")
        self.assertEqual(deep["path"], "技术标/通用素材/公司介绍/2024/Q1/深层.docx")

    def test_customer_and_project_identity_backfill(self) -> None:
        payload = tmi._build_payload(_tree(), _files())
        customer = next(t for t in payload["tiers"] if t["name"] == "客户素材")["folders"][0]
        self.assertEqual(customer["customerName"], "华能集团")
        self.assertEqual(customer["projectId"], "")

        project = next(t for t in payload["tiers"] if t["name"] == "项目素材")["folders"][0]
        self.assertEqual(project["projectId"], "MAT-HN-001")
        self.assertEqual(project["customerName"], "")
        self.assertEqual(project["fileCount"], 0)

    def test_stray_second_level_file_is_excluded(self) -> None:
        payload = tmi._build_payload(_tree(), _files())
        general = next(t for t in payload["tiers"] if t["name"] == "通用素材")
        all_ids = {f["id"] for folder in general["folders"] for f in folder["files"]}
        self.assertNotIn("RAW-0009", all_ids)

    def test_unknown_second_level_folder_is_excluded_from_wiki_index(self) -> None:
        tree = {
            "tree": [
                {
                    "name": "技术标",
                    "path": "技术标",
                    "children": [
                        {
                            "name": "国电投",
                            "path": "技术标/国电投",
                            "folderId": 100,
                            "children": [],
                        },
                        {
                            "name": "标准文件",
                            "path": "技术标/标准文件",
                            "folderId": 200,
                            "children": [
                                {"name": "EW6.25", "path": "技术标/标准文件/EW6.25", "folderId": 201, "children": []},
                            ],
                        },
                    ],
                }
            ]
        }
        files = [
            {"id": "RAW-0751", "name": "技术评审因素内容摘要.docx", "folderPath": "技术标/国电投", "ext": "docx"},
            {"id": "RAW-0752", "name": "深层资料.docx", "folderPath": "技术标/国电投/审查项", "ext": "docx"},
            {"id": "RAW-0753", "name": "总体方案.docx", "folderPath": "技术标/标准文件/EW6.25", "ext": "docx"},
        ]

        payload = tmi._build_payload(tree, files)

        self.assertEqual(payload["stats"]["tierCount"], 1)
        self.assertEqual(payload["stats"]["thirdLevelFolderCount"], 1)
        self.assertEqual(payload["stats"]["fileCount"], 1)
        standard = payload["tiers"][0]
        self.assertEqual(standard["name"], "标准文件")
        self.assertEqual(standard["tier"], "standard")
        folder_names = [folder["name"] for folder in standard["folders"]]
        self.assertEqual(folder_names, ["EW6.25"])
        all_ids = {file["id"] for folder in standard["folders"] for file in folder["files"]}
        self.assertEqual(all_ids, {"RAW-0753"})


class TechnicalMaterialWritePathTests(unittest.TestCase):
    def test_write_path_allows_only_three_technical_roots(self) -> None:
        self.assertEqual(
            ensure_technical_material_write_path("技术标/标准文件/EW6.25"),
            "技术标/标准文件/EW6.25",
        )
        self.assertEqual(
            ensure_technical_material_write_path("技术标/客户定制/华能"),
            "技术标/客户定制/华能",
        )
        self.assertEqual(
            ensure_technical_material_write_path("技术标/项目定制/MAT-001"),
            "技术标/项目定制/MAT-001",
        )
        self.assertEqual(
            ensure_technical_material_write_path("技术标/项目素材/MAT-001"),
            "技术标/项目定制/MAT-001",
        )
        with self.assertRaises(PeripheralError):
            ensure_technical_material_write_path("技术标/国电投")
        with self.assertRaises(PeripheralError):
            ensure_technical_material_write_path("技术标/通用素材")

    def test_root_child_creation_only_allows_three_technical_roots(self) -> None:
        self.assertEqual(
            ensure_technical_material_new_child_path("技术标", "标准文件"),
            "技术标",
        )
        self.assertEqual(
            canonical_technical_material_child_name("技术标", "项目素材"),
            "项目定制",
        )
        with self.assertRaises(PeripheralError):
            ensure_technical_material_new_child_path("技术标", "国电投")

    def test_technical_material_tier_roots_use_customized_names(self) -> None:
        self.assertEqual(material_tier_root_path(TECHNICAL_BID_TYPE, "standard"), "技术标/标准文件")
        self.assertEqual(material_tier_root_path(TECHNICAL_BID_TYPE, "customer"), "技术标/客户定制")
        self.assertEqual(material_tier_root_path(TECHNICAL_BID_TYPE, "project"), "技术标/项目定制")


class WriteAndLoadTests(unittest.TestCase):
    def test_write_then_load_roundtrip(self) -> None:
        with TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "_runtime" / "materials" / "technical_material_index.json"
            with patch.object(tmi, "TECHNICAL_MATERIAL_INDEX_PATH", index_path):
                payload = tmi._build_payload(_tree(), _files())
                tmi._write_index(payload)
                self.assertTrue(index_path.exists())

                on_disk = json.loads(index_path.read_text(encoding="utf-8"))
                self.assertEqual(on_disk["stats"]["fileCount"], 3)

                loaded = tmi.load_technical_material_index()
                self.assertEqual(loaded["stats"], on_disk["stats"])

    def test_load_missing_returns_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "missing.json"
            with patch.object(tmi, "TECHNICAL_MATERIAL_INDEX_PATH", index_path):
                self.assertEqual(tmi.load_technical_material_index(), {})

    def test_strict_rebuild_raises_while_best_effort_rebuild_stays_compatible(self) -> None:
        with patch.object(
            tmi,
            "_rebuild_payload",
            new=AsyncMock(side_effect=RuntimeError("index rebuild failed")),
        ):
            with self.assertRaisesRegex(RuntimeError, "index rebuild failed"):
                asyncio.run(tmi.rebuild_technical_material_index_strict())

        with patch.object(
            tmi,
            "rebuild_technical_material_index_strict",
            new=AsyncMock(side_effect=RuntimeError("index rebuild failed")),
        ):
            self.assertEqual(asyncio.run(tmi.rebuild_technical_material_index()), {})


@unittest.skipUnless(os.getenv("BID_RUN_INTEGRATION") == "1", "requires PostgreSQL, MinIO, and Redis")
class TechnicalMaterialIndexIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """端到端：建 3 级目录 + 上传后，索引随之更新；rebuild 失败不阻断主流程。"""

    async def test_rebuild_after_create_and_upload(self) -> None:
        from app.services.technical_material_store import technical_material_store

        with TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "technical_material_index.json"
            with patch.object(tmi, "TECHNICAL_MATERIAL_INDEX_PATH", index_path):
                await technical_material_store.raw_create_folder("技术标/通用素材", "集成测试目录")
                self.assertTrue(index_path.exists())
                payload = json.loads(index_path.read_text(encoding="utf-8"))
                paths = {
                    folder["path"]
                    for tier in payload["tiers"]
                    for folder in tier["folders"]
                }
                self.assertIn("技术标/通用素材/集成测试目录", paths)

    async def test_rebuild_failure_does_not_break_operation(self) -> None:
        from app.services.technical_material_store import technical_material_store

        with patch.object(
            tmi,
            "rebuild_technical_material_index",
            side_effect=RuntimeError("boom"),
        ):
            # 即便索引重建抛错，建目录主流程也应正常返回。
            result = await technical_material_store.raw_create_folder("技术标/通用素材", "容错测试目录")
            self.assertIn("tree", result)


if __name__ == "__main__":
    unittest.main()
