from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.services.technical_wiki_generation import (
    TECHNICAL_WIKI_ROOT_TITLE,
    TECHNICAL_WIKI_SKILL_NAME,
    generate_technical_wiki,
    mirror_technical_index_to_wiki,
)


def _skill_payload() -> dict:
    return {
        "summary": "技术标 Wiki 已镜像三级目录。",
        "rootTitle": TECHNICAL_WIKI_ROOT_TITLE,
        "skill": TECHNICAL_WIKI_SKILL_NAME,
        "nodes": [
            {
                "title": "01-标准文件",
                "markdownContent": "# 标准文件",
                "tags": ["技术标", "标准文件", "档位"],
                "applicableTypes": ["技术标"],
                "children": [],
            }
        ],
        "opencodeOutput": {
            "status": "received",
            "sessionId": "manifest-tech-wiki",
            "providerId": "local-skill",
            "modelId": TECHNICAL_WIKI_SKILL_NAME,
            "parts": [{"type": "text", "text": "{}"}],
        },
    }


class TechnicalWikiGenerationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_parsed_dir = settings.parsed_dir
        settings.parsed_dir = Path(self.temp_dir.name) / "parsed"
        settings.parsed_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        settings.parsed_dir = self.original_parsed_dir
        self.temp_dir.cleanup()

    async def test_generate_technical_wiki_mirrors_index_without_llm(self) -> None:
        index_payload = {
            "bidType": "技术标",
            "stats": {"tierCount": 1, "thirdLevelFolderCount": 2, "fileCount": 3},
            "tiers": [{"name": "标准文件", "tier": "standard", "folders": []}],
        }

        with (
            patch(
                "app.services.technical_wiki_generation.rebuild_technical_material_index",
                new_callable=AsyncMock,
                return_value=index_payload,
            ) as rebuild,
            patch(
                "app.services.technical_wiki_generation.run_local_wiki_skill",
                return_value=_skill_payload(),
            ) as run_skill,
            patch(
                "app.services.technical_wiki_generation.technical_material_store.import_generated_wiki_blueprint",
                new_callable=AsyncMock,
                return_value={"message": "技术标 Wiki 创建成功。", "tree": [], "selectedNode": None},
            ) as import_blueprint,
        ):
            result = await generate_technical_wiki(mode="replace")

        rebuild.assert_awaited_once()
        self.assertEqual(rebuild.await_args.kwargs["preview_mode"], "cached")
        # 走确定性脚本，不调 LLM。
        run_skill.assert_called_once()
        self.assertEqual(run_skill.call_args.kwargs["skill_name"], TECHNICAL_WIKI_SKILL_NAME)
        manifest_path = run_skill.call_args.args[0]
        self.assertIn(str(settings.parsed_dir / "_wiki_build"), str(manifest_path))

        import_blueprint.assert_awaited_once()
        self.assertEqual(import_blueprint.call_args.kwargs["root_title"], TECHNICAL_WIKI_ROOT_TITLE)
        self.assertEqual(import_blueprint.call_args.kwargs["mode"], "replace")
        self.assertEqual(import_blueprint.call_args.kwargs["nodes"][0]["title"], "01-标准文件")

        self.assertEqual(result["generation"]["generator"], "technical_index_mirror")
        self.assertEqual(result["generation"]["bidType"], "技术标")
        self.assertEqual(result["generation"]["skill"], TECHNICAL_WIKI_SKILL_NAME)
        self.assertFalse(result["generation"]["fallbackUsed"])
        self.assertEqual(result["generation"]["materialIndex"]["fileCount"], 3)

    async def test_generate_technical_wiki_falls_back_to_snapshot_when_rebuild_empty(self) -> None:
        snapshot = {
            "bidType": "技术标",
            "stats": {"tierCount": 1, "thirdLevelFolderCount": 0, "fileCount": 0},
            "tiers": [{"name": "标准文件", "tier": "standard", "folders": []}],
        }

        with (
            patch(
                "app.services.technical_wiki_generation.rebuild_technical_material_index",
                new_callable=AsyncMock,
                return_value={"tiers": []},
            ),
            patch(
                "app.services.technical_wiki_generation.load_technical_material_index",
                return_value=snapshot,
            ) as load_snapshot,
            patch(
                "app.services.technical_wiki_generation.run_local_wiki_skill",
                return_value=_skill_payload(),
            ),
            patch(
                "app.services.technical_wiki_generation.technical_material_store.import_generated_wiki_blueprint",
                new_callable=AsyncMock,
                return_value={"message": "ok", "tree": [], "selectedNode": None},
            ),
        ):
            result = await generate_technical_wiki(mode="create")

        load_snapshot.assert_called_once()
        self.assertEqual(result["generation"]["generator"], "technical_index_mirror")

    async def test_mirror_loads_full_blueprint_from_output_file(self) -> None:
        output_file = settings.parsed_dir / "wiki_blueprint.json"
        output_file.write_text(
            """{
  "summary": "完整技术标 Wiki。",
  "rootTitle": "技术标Wiki（自动生成）",
  "nodes": [
    {
      "title": "02-客户定制",
      "markdownContent": "# 客户定制",
      "tags": ["技术标", "客户定制"],
      "applicableTypes": ["技术标"],
      "children": [
        {"title": "华能", "markdownContent": "# 华能", "tags": ["客户"], "applicableTypes": ["技术标"], "children": []}
      ]
    }
  ]
}""",
            encoding="utf-8",
        )
        skill_result = {
            "schema_version": "bid-wiki-blueprint-v2",
            "skill": TECHNICAL_WIKI_SKILL_NAME,
            "summary": "stdout 摘要",
            "rootTitle": TECHNICAL_WIKI_ROOT_TITLE,
            "outputFile": str(output_file),
            "nodes": [],
            "opencodeOutput": {"status": "received", "sessionId": "ses-tech"},
        }

        with (
            patch(
                "app.services.technical_wiki_generation.run_local_wiki_skill",
                return_value=skill_result,
            ),
            patch(
                "app.services.technical_wiki_generation.technical_material_store.import_generated_wiki_blueprint",
                new_callable=AsyncMock,
                return_value={"message": "ok", "tree": [], "selectedNode": None},
            ) as import_blueprint,
        ):
            result = await mirror_technical_index_to_wiki(
                {"bidType": "技术标", "stats": {"fileCount": 1}, "tiers": [{"tier": "customer"}]},
                mode="replace",
            )

        imported_nodes = import_blueprint.call_args.kwargs["nodes"]
        self.assertEqual(result["generation"]["summary"], "完整技术标 Wiki。")
        self.assertEqual(imported_nodes[0]["title"], "02-客户定制")
        self.assertEqual(imported_nodes[0]["children"][0]["title"], "华能")


if __name__ == "__main__":
    unittest.main()
