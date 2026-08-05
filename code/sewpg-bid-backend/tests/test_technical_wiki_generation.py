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
from app.services.technical_wiki_preview_generation import enrich_technical_wiki_previews


def _skill_payload() -> dict:
    return {
        "summary": "技术标 Wiki 已镜像三级目录。",
        "rootTitle": TECHNICAL_WIKI_ROOT_TITLE,
        "skill": TECHNICAL_WIKI_SKILL_NAME,
        "nodes": [
            {
                "title": "标准文件",
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

    async def test_generate_technical_wiki_mirrors_existing_index_without_llm(self) -> None:
        index_payload = {
            "bidType": "技术标",
            "stats": {"tierCount": 1, "thirdLevelFolderCount": 2, "fileCount": 3},
            "tiers": [{"name": "标准文件", "tier": "standard", "folders": []}],
        }

        with (
            patch(
                "app.services.technical_wiki_generation.load_technical_material_index",
                return_value=index_payload,
            ) as load_index,
            patch(
                "app.services.technical_wiki_generation.enrich_technical_wiki_previews",
                new_callable=AsyncMock,
                return_value={
                    "enabled": True,
                    "total": 3,
                    "completed": 2,
                    "cached": 1,
                    "skipped": 0,
                    "failed": 1,
                    "errors": [{"fileId": "RAW-0003", "message": "LLM 批量回复缺该文件或无效"}],
                    "batchCount": 1,
                },
            ) as enrich_previews,
            patch("app.services.technical_wiki_generation.write_json_file_atomic") as write_index,
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

        load_index.assert_called_once()
        enrich_previews.assert_awaited_once_with(index_payload, on_progress=None)
        write_index.assert_called_once()
        # 走确定性脚本，不调 LLM。
        run_skill.assert_called_once()
        self.assertEqual(run_skill.call_args.kwargs["skill_name"], TECHNICAL_WIKI_SKILL_NAME)
        manifest_path = run_skill.call_args.args[0]
        self.assertIn(str(settings.parsed_dir / "_wiki_build"), str(manifest_path))

        import_blueprint.assert_awaited_once()
        self.assertEqual(import_blueprint.call_args.kwargs["root_title"], TECHNICAL_WIKI_ROOT_TITLE)
        self.assertEqual(import_blueprint.call_args.kwargs["mode"], "replace")
        self.assertEqual(import_blueprint.call_args.kwargs["nodes"][0]["title"], "标准文件")

        self.assertEqual(result["generation"]["generator"], "technical_index_mirror")
        self.assertEqual(result["generation"]["bidType"], "技术标")
        self.assertEqual(result["generation"]["skill"], TECHNICAL_WIKI_SKILL_NAME)
        self.assertFalse(result["generation"]["fallbackUsed"])
        self.assertEqual(result["generation"]["materialIndex"]["fileCount"], 3)
        self.assertEqual(result["generation"]["preview"]["failed"], 1)
        self.assertIn("失败 1 个", result["generation"]["summary"])

    async def test_generate_technical_wiki_rejects_missing_index(self) -> None:
        with patch(
            "app.services.technical_wiki_generation.load_technical_material_index",
            return_value={},
        ), patch(
            "app.services.technical_wiki_generation.enrich_technical_wiki_previews",
            new_callable=AsyncMock,
        ) as enrich_previews:
            with self.assertRaisesRegex(RuntimeError, "technical_material_index.json"):
                await generate_technical_wiki(mode="create")
        enrich_previews.assert_not_awaited()

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

    async def test_enrich_previews_applies_success_and_fallbacks(self) -> None:
        index_payload = {
            "tiers": [
                {
                    "name": "标准文件",
                    "tier": "standard",
                    "folders": [
                        {
                            "name": "EW5.0",
                            "files": [
                                {"id": "RAW-0001", "name": "总体方案.docx"},
                                {"id": "RAW-0002", "name": "载荷报告.docx", "preview": {"lead": "旧预览"}},
                            ],
                        }
                    ],
                }
            ]
        }
        completed_payload = {
            "schemaVersion": 1,
            "signature": "sig-1",
            "status": "completed",
            "retryable": False,
            "metadata": {"cleanStatus": "cleaned"},
            "evidenceSegments": [
                {
                    "segmentId": "tech-seg-overall",
                    "materialId": "RAW-0001",
                    "title": "总体方案",
                    "summary": "设计依据",
                }
            ],
            "documentOutline": [
                {"level": 1, "title": "总体方案"},
                {"level": 2, "title": "设计依据"},
            ],
            "preview": {
                "lead": "总体方案导读",
                "points": ["包含设计依据"],
                "keyParams": [],
                "retrievalHints": ["总体方案"],
            },
        }
        failed_payload = {
            "schemaVersion": 1,
            "signature": "sig-2",
            "status": "fallback",
            "skipReason": "LLM 批量回复缺该文件或无效",
            "retryable": True,
            "metadata": {"cleanStatus": "cleaned"},
            "evidenceSegments": [
                {
                    "segmentId": "tech-seg-load",
                    "materialId": "RAW-0002",
                    "title": "载荷报告",
                    "summary": "载荷分析",
                }
            ],
            "documentOutline": [],
            "preview": {
                "lead": "载荷报告本地 TLDR",
                "points": ["AI 预览未完成，当前为本地 TLDR"],
                "keyParams": [{"label": "文件类型", "value": "docx"}],
                "retrievalHints": ["载荷报告"],
                "source": "local",
            },
        }

        with (
            patch(
                "app.services.technical_wiki_preview_generation._build_preview_plans",
                new_callable=AsyncMock,
                return_value=(
                    [
                        {"fileId": "RAW-0001", "payload": completed_payload},
                        {"fileId": "RAW-0002", "payload": failed_payload},
                    ],
                    {"total": 2, "completed": 0, "cached": 0, "skipped": 0, "failed": 0, "errors": []},
                ),
            ),
            patch(
                "app.services.technical_wiki_preview_generation._persist_preview_payloads",
                new_callable=AsyncMock,
            ) as persist_payloads,
        ):
            stats = await enrich_technical_wiki_previews(index_payload)

        files = index_payload["tiers"][0]["folders"][0]["files"]
        self.assertEqual(files[0]["preview"]["lead"], "总体方案导读")
        self.assertEqual(files[0]["evidenceSegments"][0]["materialId"], "RAW-0001")
        # 索引不再承载 cleanStatus，预览元数据也不得把它写回索引。
        self.assertNotIn("cleanStatus", files[0])
        self.assertEqual(files[0]["documentOutline"][1]["title"], "设计依据")
        self.assertEqual(files[0]["previewStatus"], "completed")
        self.assertFalse(files[0]["previewRetryable"])
        self.assertEqual(files[1]["preview"]["lead"], "载荷报告本地 TLDR")
        self.assertEqual(files[1]["evidenceSegments"][0]["materialId"], "RAW-0002")
        self.assertNotIn("cleanStatus", files[1])
        self.assertEqual(files[1]["documentOutline"], [])
        self.assertEqual(files[1]["previewStatus"], "fallback")
        self.assertTrue(files[1]["previewRetryable"])
        self.assertEqual(files[1]["previewError"], "LLM 批量回复缺该文件或无效")
        persist_payloads.assert_awaited_once()
        self.assertEqual(persist_payloads.await_args.args[0]["RAW-0001"], completed_payload)
        self.assertEqual(persist_payloads.await_args.args[0]["RAW-0002"], failed_payload)
        self.assertTrue(stats["enabled"])
        self.assertEqual(stats["completed"], 1)
        self.assertEqual(stats["fallback"], 1)
        self.assertEqual(stats["retryable"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(stats["errors"][0]["fileId"], "RAW-0002")


if __name__ == "__main__":
    unittest.main()
