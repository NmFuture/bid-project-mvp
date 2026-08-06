"""Wiki 导入进度计数（进度条「建树导入」段 m/n）单测。"""
from __future__ import annotations

import unittest

from app.services.material_wiki_import_operations import count_wiki_node_specs


class WikiImportProgressTests(unittest.TestCase):
    def test_counts_all_levels(self) -> None:
        specs = [
            {"title": "档位A", "children": [
                {"title": "目录1", "children": [{"title": "文件1"}, {"title": "文件2"}]},
                {"title": "目录2"},
            ]},
            {"title": "档位B"},
        ]
        # 2 档位 + 2 目录 + 2 文件 = 6，分母覆盖所有层级而不只是顶层。
        self.assertEqual(count_wiki_node_specs(specs), 6)

    def test_ignores_non_dict_and_empty(self) -> None:
        self.assertEqual(count_wiki_node_specs([]), 0)
        self.assertEqual(count_wiki_node_specs([{"title": "A", "children": ["脏数据", None]}]), 1)


if __name__ == "__main__":
    unittest.main()
