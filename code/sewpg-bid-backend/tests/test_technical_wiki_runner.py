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
                "cleanStatus": "cleaned",
                "preview": {
                    "lead": "用于 EW5.0 技术方案编制的总体说明。",
                    "points": ["覆盖设计依据", "包含关键参数"],
                    "keyParams": [{"label": "功率", "value": "5MW"}],
                    "retrievalHints": ["总体方案", "EW5.0"],
                },
            },
            "standard",
            {"name": "EW5.0"},
        )

        self.assertIn("## TLDR 文件信息卡片", card["markdownContent"])
        self.assertIn("来源：AI 生成", card["markdownContent"])
        self.assertIn("用于 EW5.0 技术方案编制的总体说明。", card["markdownContent"])
        self.assertIn("| 功率 | 5MW |", card["markdownContent"])
        self.assertIn("- EW5.0", card["markdownContent"])
        self.assertIn("内容预览", card["tags"])
        self.assertIn("## 文件定位", card["markdownContent"])

    def test_file_card_without_preview_keeps_structure_index_notice(self) -> None:
        card = RUNNER.build_file_card(
            {
                "id": "RAW-0002",
                "name": "空白材料.pdf",
                "path": "技术标/标准文件/EW5.0/空白材料.pdf",
                "ext": "pdf",
                "cleanStatus": "pending",
            },
            "standard",
            {"name": "EW5.0"},
        )

        self.assertNotIn("## TLDR 文件信息卡片", card["markdownContent"])
        self.assertNotIn("内容预览", card["tags"])
        self.assertIn("本卡片仅为三级目录结构索引", card["markdownContent"])


if __name__ == "__main__":
    unittest.main()
