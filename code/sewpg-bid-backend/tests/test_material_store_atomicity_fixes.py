"""素材库审查修复的聚焦回归测试（H4 / M3 / M4 / L4）。

只覆盖可无 DB / 无 MinIO 纯逻辑验证的修复点，独立文件，不改动既有测试。
"""
from __future__ import annotations

import asyncio
import unittest

from app.services import technical_material_index as tmi
from app.services.technical_material_paths import (
    TECHNICAL_ALLOWED_WRITE_ROOTS,
    ensure_technical_material_write_path,
)
from app.services.peripheral import PeripheralError


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class SetTagsMergeTests(unittest.TestCase):
    """H4：commit 阶段 merge=True 时在锁内 read-merge-write，取并集不丢标签。"""

    def setUp(self) -> None:
        # 用内存节点替换索引读写，隔离文件 IO
        self._node = {"id": "RAW-0001", "tags": ["现存标签A", "现存标签B"]}
        self._written = []

        def fake_load():
            return {"items": [self._node]}

        def fake_match_file(target, payload):
            return self._node if target == self._node["id"] else None

        def fake_write(payload):
            self._written.append(payload)

        self._orig = (
            tmi.load_technical_material_index,
            tmi._match_file,
            tmi._write_index,
        )
        tmi.load_technical_material_index = fake_load
        tmi._match_file = fake_match_file
        tmi._write_index = fake_write

    def tearDown(self) -> None:
        (
            tmi.load_technical_material_index,
            tmi._match_file,
            tmi._write_index,
        ) = self._orig

    def test_merge_true_takes_union_with_current_tags(self) -> None:
        # 传入的是 preview 快照（只含 A + 新增C），期间他人加了 B；merge 应保留 B
        node = _run(
            tmi.set_tags_for_node(target_id="RAW-0001", tags=["现存标签A", "新增标签C"], merge=True)
        )
        self.assertIn("现存标签B", node["tags"], "merge=True 必须保留期间新增的标签（H4）")
        self.assertIn("现存标签A", node["tags"])
        self.assertIn("新增标签C", node["tags"])

    def test_merge_false_replaces_tags(self) -> None:
        node = _run(
            tmi.set_tags_for_node(target_id="RAW-0001", tags=["仅覆盖标签"], merge=False)
        )
        self.assertEqual(node["tags"], ["仅覆盖标签"], "merge=False 保持整条覆盖语义")


class WritePathWhitelistTests(unittest.TestCase):
    """M4：切分 fragment 落盘走与手工 confirm 相同的写目录白名单校验。"""

    def test_alias_is_rewritten_to_canonical_root(self) -> None:
        # 旧名"项目素材"应被重写为"项目定制"
        result = ensure_technical_material_write_path("技术标/项目素材/某项目", "切分目标目录")
        self.assertTrue(result.startswith("技术标/项目定制"))

    def test_out_of_whitelist_path_raises(self) -> None:
        # 白名单外目录必须抛错（splitter 捕获后回落）
        with self.assertRaises(PeripheralError):
            ensure_technical_material_write_path("技术标/通用素材/乱写", "切分目标目录")

    def test_fallback_root_is_in_whitelist(self) -> None:
        # splitter 回落根"标准文件"必须在白名单内
        self.assertIn("标准文件", TECHNICAL_ALLOWED_WRITE_ROOTS)


if __name__ == "__main__":
    unittest.main()
