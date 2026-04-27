from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.services.peripheral import PeripheralError
from app.services.wiki_generation import generate_platform_wiki


class WikiGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_platform_wiki_uses_opencode_blueprint(self) -> None:
        opencode_payload = {
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
                "sessionId": "ses-wiki",
                "providerId": "opencode",
                "modelId": "big-pickle",
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
                "app.services.wiki_generation.OpencodeClient.generate_wiki_blueprint_with_trace",
                return_value=opencode_payload,
            ) as generate,
            patch(
                "app.services.wiki_generation.material_store.import_generated_wiki_blueprint",
                new_callable=AsyncMock,
                return_value={"message": "平台级 Wiki 创建成功。", "tree": [], "selectedNode": None},
            ) as import_blueprint,
        ):
            result = await generate_platform_wiki(mode="replace")

        generate.assert_called_once()
        prompt = generate.call_args.args[0]
        self.assertIn("Use the bid-tech-wiki-material-builder skill.", prompt)
        import_blueprint.assert_awaited_once()
        self.assertEqual(import_blueprint.call_args.kwargs["root_title"], "技术标Wiki（自动生成）")
        self.assertEqual(import_blueprint.call_args.kwargs["nodes"][0]["title"], "00-Wiki使用说明")
        self.assertEqual(result["generation"]["generator"], "opencode")
        self.assertEqual(result["generation"]["bidType"], "技术标")
        self.assertEqual(result["generation"]["skill"], "bid-tech-wiki-material-builder")
        self.assertFalse(result["generation"]["fallbackUsed"])
        self.assertEqual(result["generation"]["opencodeOutput"]["sessionId"], "ses-wiki")

    async def test_generate_business_wiki_uses_business_skill_and_inventory(self) -> None:
        opencode_payload = {
            "summary": "商务标 Wiki 已由 skill 生成。",
            "rootTitle": "商务标Wiki（自动生成）",
            "nodes": [
                {
                    "title": "00-Wiki使用说明",
                    "markdownContent": "# 00-Wiki使用说明\n\n由商务标 skill 生成。",
                    "tags": ["商务标"],
                    "applicableTypes": ["商务标"],
                    "children": [],
                }
            ],
            "opencodeOutput": {
                "status": "received",
                "sessionId": "ses-business-wiki",
                "providerId": "opencode",
                "modelId": "big-pickle",
                "parts": [{"type": "text", "text": "{\"summary\":\"商务标 Wiki 已由 skill 生成。\"}"}],
            },
        }
        inventory = {
            "total": 2,
            "docxTotal": 2,
            "parsedDocxTotal": 2,
            "groups": {},
            "items": [
                {
                    "name": "技术资料.docx",
                    "title": "技术资料",
                    "path": "通用素材/技术标/技术资料.docx",
                    "ext": "docx",
                    "bidType": "技术标",
                    "scope": "通用",
                    "group": "总体方案",
                },
                {
                    "name": "商务资料.docx",
                    "title": "商务资料",
                    "path": "通用素材/商务标/商务资料.docx",
                    "ext": "docx",
                    "bidType": "商务标",
                    "scope": "通用",
                    "group": "商务通用",
                },
            ],
        }

        with (
            patch(
                "app.services.wiki_generation._summarize_material_inventory",
                new_callable=AsyncMock,
                return_value=inventory,
            ),
            patch(
                "app.services.wiki_generation.OpencodeClient.generate_wiki_blueprint_with_trace",
                return_value=opencode_payload,
            ) as generate,
            patch(
                "app.services.wiki_generation.material_store.import_generated_wiki_blueprint",
                new_callable=AsyncMock,
                return_value={"message": "商务标 Wiki 创建成功。", "tree": [], "selectedNode": None},
            ) as import_blueprint,
        ):
            result = await generate_platform_wiki(mode="replace", bid_type="商务标")

        prompt = generate.call_args.args[0]
        self.assertIn("Use the bid-business-wiki-material-builder skill.", prompt)
        self.assertIn("商务资料.docx", prompt)
        self.assertNotIn("技术资料.docx", prompt)
        self.assertEqual(import_blueprint.call_args.kwargs["root_title"], "商务标Wiki（自动生成）")
        self.assertEqual(result["generation"]["bidType"], "商务标")
        self.assertEqual(result["generation"]["skill"], "bid-business-wiki-material-builder")

    async def test_generate_platform_wiki_fails_without_silent_fallback(self) -> None:
        with (
            patch(
                "app.services.wiki_generation._summarize_material_inventory",
                new_callable=AsyncMock,
                return_value={"total": 0, "docxTotal": 0, "parsedDocxTotal": 0, "groups": {}, "items": []},
            ),
            patch(
                "app.services.wiki_generation.OpencodeClient.generate_wiki_blueprint_with_trace",
                side_effect=RuntimeError("opencode 不可用"),
            ),
            patch(
                "app.services.wiki_generation.material_store.import_generated_wiki_blueprint",
                new_callable=AsyncMock,
            ) as import_blueprint,
        ):
            with self.assertRaises(PeripheralError) as context:
                await generate_platform_wiki()

        self.assertEqual(context.exception.code, "WIKI_OPENCODE_FAILED")
        import_blueprint.assert_not_awaited()

    async def test_generate_platform_wiki_can_use_explicit_deterministic_fallback(self) -> None:
        with (
            patch(
                "app.services.wiki_generation._summarize_material_inventory",
                new_callable=AsyncMock,
                return_value={"total": 0, "docxTotal": 0, "parsedDocxTotal": 0, "groups": {}, "items": []},
            ),
            patch(
                "app.services.wiki_generation.OpencodeClient.generate_wiki_blueprint_with_trace",
                side_effect=RuntimeError("opencode 不可用"),
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
