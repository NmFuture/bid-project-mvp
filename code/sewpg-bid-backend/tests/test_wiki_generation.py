from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.services.peripheral import PeripheralError
from app.services.wiki_generation import generate_platform_wiki


class WikiGenerationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_parsed_dir = settings.parsed_dir
        settings.parsed_dir = Path(self.temp_dir.name) / "parsed"
        settings.parsed_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        settings.parsed_dir = self.original_parsed_dir
        self.temp_dir.cleanup()

    async def test_generate_platform_wiki_uses_local_skill_blueprint(self) -> None:
        skill_payload = {
            "summary": "Wiki 已由 skill 生成。",
            "rootTitle": "技术标Wiki（自动生成）",
            "nodes": [
                {
                    "title": "00-Wiki使用说明",
                    "markdownContent": "# 00-Wiki使用说明\n\n由 skill 生成。",
                    "tags": ["技术标", "素材库"],
                    "applicableTypes": ["技术标"],
                    "children": [],
                }
            ],
            "opencodeOutput": {
                "status": "received",
                "sessionId": "manifest-wiki",
                "providerId": "local-skill",
                "modelId": "bid-tech-wiki-material-builder",
                "parts": [{"type": "text", "text": "{\"summary\":\"Wiki 已由 skill 生成。\"}"}],
            },
        }

        with (
            patch(
                "app.services.wiki_generation._summarize_material_inventory",
                new_callable=AsyncMock,
                return_value={"total": 1, "docxTotal": 1, "parsedDocxTotal": 1, "groups": {}, "items": []},
            ),
            patch(
                "app.services.wiki_generation._run_local_wiki_skill",
                return_value=skill_payload,
            ) as generate,
            patch(
                "app.services.wiki_generation.material_store.import_generated_wiki_blueprint",
                new_callable=AsyncMock,
                return_value={"message": "平台级 Wiki 创建成功。", "tree": [], "selectedNode": None},
            ) as import_blueprint,
        ):
            result = await generate_platform_wiki(mode="replace")

        generate.assert_called_once()
        manifest_path = generate.call_args.args[0]
        self.assertIn(str(settings.parsed_dir / "_wiki_build"), str(manifest_path))
        import_blueprint.assert_awaited_once()
        self.assertEqual(import_blueprint.call_args.kwargs["root_title"], "技术标Wiki（自动生成）")
        self.assertEqual(import_blueprint.call_args.kwargs["nodes"][0]["title"], "00-Wiki使用说明")
        self.assertEqual(result["generation"]["generator"], "local_skill")
        self.assertEqual(result["generation"]["bidType"], "技术标")
        self.assertEqual(result["generation"]["skill"], "bid-tech-wiki-material-builder")
        self.assertFalse(result["generation"]["fallbackUsed"])
        self.assertEqual(result["generation"]["opencodeOutput"]["sessionId"], "manifest-wiki")

    async def test_generate_business_wiki_is_disabled_for_now(self) -> None:
        with self.assertRaises(PeripheralError) as ctx:
            await generate_platform_wiki(mode="replace", bid_type="商务标")

        self.assertEqual(ctx.exception.code, "BUSINESS_WIKI_DISABLED")

    async def test_generate_platform_wiki_loads_full_blueprint_from_output_file(self) -> None:
        output_file = settings.parsed_dir / "wiki_blueprint.json"
        output_file.write_text(
            """{
  "summary": "完整 Wiki 已生成。",
  "rootTitle": "技术标Wiki（自动生成）",
  "nodes": [
    {
      "title": "03-素材卡片",
      "markdownContent": "# 03-素材卡片",
      "tags": ["技术标"],
      "applicableTypes": ["技术标"],
      "children": [
        {
          "title": "通用素材",
          "markdownContent": "# 通用素材",
          "tags": ["通用素材"],
          "applicableTypes": ["技术标"],
          "children": [
            {"title": "总体方案", "markdownContent": "# 总体方案", "tags": ["素材卡片"], "applicableTypes": ["技术标"], "children": []}
          ]
        }
      ]
    }
  ]
}""",
            encoding="utf-8",
        )
        opencode_payload = {
            "schema_version": "bid-wiki-blueprint-v1",
            "summary": "stdout 摘要",
            "rootTitle": "技术标Wiki（自动生成）",
            "outputFile": str(output_file),
            "nodes": [],
            "opencodeOutput": {"status": "received", "sessionId": "ses-wiki", "earlyCompletion": True},
        }

        with (
            patch(
                "app.services.wiki_generation._summarize_material_inventory",
                new_callable=AsyncMock,
                return_value={"total": 1, "docxTotal": 1, "parsedDocxTotal": 1, "groups": {}, "items": []},
            ),
            patch(
                "app.services.wiki_generation._run_local_wiki_skill",
                return_value=opencode_payload,
            ),
            patch(
                "app.services.wiki_generation.material_store.import_generated_wiki_blueprint",
                new_callable=AsyncMock,
                return_value={"message": "平台级 Wiki 创建成功。", "tree": [], "selectedNode": None},
            ) as import_blueprint,
        ):
            result = await generate_platform_wiki(mode="replace")

        imported_nodes = import_blueprint.call_args.kwargs["nodes"]
        self.assertEqual(result["generation"]["summary"], "完整 Wiki 已生成。")
        self.assertEqual(imported_nodes[0]["title"], "03-素材卡片")
        self.assertEqual(imported_nodes[0]["children"][0]["children"][0]["title"], "总体方案")

    async def test_generate_platform_wiki_fails_without_silent_fallback(self) -> None:
        with (
            patch(
                "app.services.wiki_generation._summarize_material_inventory",
                new_callable=AsyncMock,
                return_value={"total": 0, "docxTotal": 0, "parsedDocxTotal": 0, "groups": {}, "items": []},
            ),
            patch(
                "app.services.wiki_generation._run_local_wiki_skill",
                side_effect=RuntimeError("skill 不可用"),
            ),
            patch(
                "app.services.wiki_generation.material_store.import_generated_wiki_blueprint",
                new_callable=AsyncMock,
            ) as import_blueprint,
        ):
            with self.assertRaises(PeripheralError) as context:
                await generate_platform_wiki()

        self.assertEqual(context.exception.code, "WIKI_SKILL_FAILED")
        import_blueprint.assert_not_awaited()

    async def test_generate_platform_wiki_can_use_explicit_deterministic_fallback(self) -> None:
        with (
            patch(
                "app.services.wiki_generation._summarize_material_inventory",
                new_callable=AsyncMock,
                return_value={"total": 0, "docxTotal": 0, "parsedDocxTotal": 0, "groups": {}, "items": []},
            ),
            patch(
                "app.services.wiki_generation._run_local_wiki_skill",
                side_effect=RuntimeError("skill 不可用"),
            ),
            patch(
                "app.services.wiki_generation.material_store.import_generated_wiki_blueprint",
                new_callable=AsyncMock,
                return_value={"message": "平台级 Wiki 创建成功。", "tree": [], "selectedNode": None},
            ) as import_blueprint,
        ):
            result = await generate_platform_wiki(fallback_to_deterministic=True)

        import_blueprint.assert_awaited_once()
        self.assertEqual(result["generation"]["generator"], "deterministic_fallback")
        self.assertEqual(result["generation"]["bidType"], "技术标")
        self.assertTrue(result["generation"]["fallbackUsed"])
        self.assertEqual(result["generation"]["opencodeOutput"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
