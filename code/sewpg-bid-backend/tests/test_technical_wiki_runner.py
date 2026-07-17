from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


RUNNER_PATH = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skills"
    / "bid-tech-wiki-material-builder"
    / "scripts"
    / "run_from_manifest.py"
)


def load_runner_module():
    module_name = "technical_wiki_runner_test"
    spec = importlib.util.spec_from_file_location(module_name, RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


RUNNER = load_runner_module()


class TechnicalWikiRunnerTests(unittest.TestCase):
    def test_blueprint_preserves_json_tier_order_and_names(self) -> None:
        blueprint = RUNNER.build_blueprint(
            {
                "bidType": "技术标",
                "tiers": [
                    {"name": "项目定制", "tier": "project", "folders": []},
                    {"name": "标准文件", "tier": "standard", "folders": []},
                    {"name": "客户定制", "tier": "customer", "folders": []},
                ],
            }
        )

        self.assertEqual(
            [node["title"] for node in blueprint["nodes"]],
            ["项目定制", "标准文件", "客户定制"],
        )

    def test_file_card_renders_content_preview_payload(self) -> None:
        card = RUNNER.build_file_card(
            {
                "id": "RAW-0001",
                "name": "总体方案.docx",
                "path": "技术标/标准文件/EW5.0/总体方案.docx",
                "ext": "docx",
                "previewStatus": "completed",
                "preview": {
                    "lead": "用于 EW5.0 技术方案编制的总体说明。",
                    "points": ["覆盖设计依据", "包含关键参数"],
                    "keyParams": [{"label": "功率", "value": "5MW"}],
                    "retrievalHints": ["总体方案", "EW5.0"],
                },
                "documentOutline": [
                    {"level": 1, "title": "总体方案"},
                    {"level": 2, "title": "供货范围"},
                    {"level": 3, "title": "维护计划"},
                ],
            },
            "standard",
            {"name": "EW5.0"},
        )

        self.assertIn("## TLDR 文件信息卡片", card["markdownContent"])
        self.assertIn("来源：AI 生成", card["markdownContent"])
        self.assertIn("用于 EW5.0 技术方案编制的总体说明。", card["markdownContent"])
        self.assertNotIn("### 关键参数", card["markdownContent"])
        self.assertNotIn("| 功率 | 5MW |", card["markdownContent"])
        self.assertIn("- EW5.0", card["markdownContent"])
        self.assertIn("内容预览", card["tags"])
        self.assertIn("AI预览成功", card["tags"])
        self.assertIn("## 文件定位", card["markdownContent"])
        self.assertNotIn("## 所属档位", card["markdownContent"])
        self.assertIn("## 全文目录\n\n- 总体方案\n    - 供货范围\n        - 维护计划", card["markdownContent"])
        self.assertTrue(card["markdownContent"].rstrip().endswith("- 维护计划"))

    def test_file_card_without_preview_keeps_structure_index_notice(self) -> None:
        card = RUNNER.build_file_card(
            {
                "id": "RAW-0002",
                "name": "空白材料.pdf",
                "path": "技术标/标准文件/EW5.0/空白材料.pdf",
                "ext": "pdf",
            },
            "standard",
            {"name": "EW5.0"},
        )

        self.assertNotIn("## TLDR 文件信息卡片", card["markdownContent"])
        self.assertNotIn("内容预览", card["tags"])
        self.assertIn("本卡片仅为三级目录结构索引", card["markdownContent"])
        self.assertNotIn("## 全文目录", card["markdownContent"])
        self.assertTrue(card["markdownContent"].rstrip().endswith("完整路径见上方文件定位。"))

    def test_file_card_marks_retryable_and_local_fallbacks(self) -> None:
        retryable = RUNNER.build_file_card(
            {
                "id": "RAW-0004",
                "name": "连接失败.docx",
                "ext": "docx",
                "previewStatus": "fallback",
                "previewRetryable": True,
                "preview": {"source": "local", "lead": "本地摘要"},
            },
            "standard",
            {"name": "EW5.0"},
        )
        local_only = RUNNER.build_file_card(
            {
                "id": "RAW-0005",
                "name": "超大文件.docx",
                "ext": "docx",
                "previewStatus": "fallback",
                "previewRetryable": False,
                "preview": {"source": "local", "lead": "本地摘要"},
            },
            "standard",
            {"name": "EW5.0"},
        )

        self.assertIn("AI预览待重试", retryable["tags"])
        self.assertNotIn("本地TLDR", retryable["tags"])
        self.assertIn("本地TLDR", local_only["tags"])
        self.assertNotIn("AI预览待重试", local_only["tags"])

    def test_non_word_card_never_renders_stale_outline(self) -> None:
        card = RUNNER.build_file_card(
            {
                "id": "RAW-0003",
                "name": "参数表.xlsx",
                "path": "技术标/标准文件/EW5.0/参数表.xlsx",
                "ext": "xlsx",
                "cleanStatus": "cleaned",
                "documentOutline": [{"level": 1, "title": "工作表一"}],
            },
            "standard",
            {"name": "EW5.0"},
        )

        self.assertNotIn("## 全文目录", card["markdownContent"])
        self.assertNotIn("工作表一", card["markdownContent"])

    def test_folder_node_restores_deep_hierarchy_from_file_paths(self) -> None:
        folder = {
            "name": "华能",
            "path": "技术标/客户定制/华能",
            "customerName": "华能",
            "fileCount": 3,
            "files": [
                {
                    "id": "RAW-0101",
                    "name": "直属文件.docx",
                    "path": "技术标/客户定制/华能/直属文件.docx",
                    "ext": "docx",
                },
                {
                    "id": "RAW-0102",
                    "name": "四级文件.docx",
                    "path": "技术标/客户定制/华能/北方公司/四级文件.docx",
                    "ext": "docx",
                },
                {
                    "id": "RAW-0103",
                    "name": "五级文件.pdf",
                    "path": "技术标/客户定制/华能/北方公司/风电项目/五级文件.pdf",
                    "ext": "pdf",
                },
            ],
        }

        node = RUNNER.build_folder_node(folder, "customer")

        # 3 级目录直接子节点 = 1 个子目录（北方公司）+ 1 个直属文件卡片
        child_titles = [child["title"] for child in node["children"]]
        self.assertEqual(child_titles, ["北方公司", "直属文件.docx"])

        subdir = node["children"][0]
        self.assertIn("子目录", subdir["tags"])
        self.assertIn("`技术标/客户定制/华能/北方公司`", subdir["markdownContent"])

        # 北方公司下：风电项目子目录 + 四级文件卡片
        sub_titles = [child["title"] for child in subdir["children"]]
        self.assertEqual(sub_titles, ["风电项目", "四级文件.docx"])

        deepest = subdir["children"][0]
        self.assertEqual([child["title"] for child in deepest["children"]], ["五级文件.pdf"])

        # 3 级目录正文的全量清单带相对路径列
        self.assertIn("| RAW-0103 | 五级文件.pdf | 北方公司/风电项目 |", node["markdownContent"])
        self.assertIn("| RAW-0101 | 直属文件.docx | — |", node["markdownContent"])

    def test_folder_node_without_deep_files_keeps_flat_children(self) -> None:
        folder = {
            "name": "EW5.0",
            "path": "技术标/标准文件/EW5.0",
            "files": [
                {
                    "id": "RAW-0001",
                    "name": "总体方案.docx",
                    "path": "技术标/标准文件/EW5.0/总体方案.docx",
                    "ext": "docx",
                },
            ],
        }

        node = RUNNER.build_folder_node(folder, "standard")
        self.assertEqual([child["title"] for child in node["children"]], ["总体方案.docx"])


if __name__ == "__main__":
    unittest.main()
