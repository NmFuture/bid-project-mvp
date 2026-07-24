from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.technical_wiki_preview_generation import (
    PREVIEW_EXT_FIELD,
    PREVIEW_LLM_MAX_FAILURES,
    _build_preview_plans,
    _compute_batch_preview_payloads,
    _preview_signature,
    enrich_technical_wiki_previews,
)
from app.services.technical_wiki_preview_prompt import PREVIEW_SCHEMA_VERSION

PROFILE = {
    "headings": [{"level": 1, "title": "总体方案"}, {"level": 2, "title": "供货范围"}],
    "paragraphs": ["本机组适用于低温环境。", "额定功率 5.0MW。"],
    "tableCount": 1,
}


def _plan(file_id: str = "RAW-0001", llm_failures: int = 0) -> dict:
    return {
        "fileId": file_id,
        "name": "总体方案.docx",
        "path": "技术标/标准文件/EW5.0/总体方案.docx",
        "tier_label": "标准文件",
        "ext": "docx",
        "clean_status": "cleaned",
        "profile": PROFILE,
        "base": {
            "schemaVersion": PREVIEW_SCHEMA_VERSION,
            "signature": "sig-1",
            "generatedAt": "2026-07-22 00:00:00",
            "documentOutline": [],
        },
        "llm_failures": llm_failures,
    }


class _ExecuteResult:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def scalars(self) -> "_ExecuteResult":
        return self

    def all(self) -> list[object]:
        return list(self._items)


class _SingleExecuteSession:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    async def __aenter__(self) -> "_SingleExecuteSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> _ExecuteResult:
        return _ExecuteResult(self._items)


def _raw_item(cached: dict | None) -> SimpleNamespace:
    ext_fields = {PREVIEW_EXT_FIELD: cached} if cached else {}
    return SimpleNamespace(
        id=1,
        name="总体方案.docx",
        ext_fields=ext_fields,
        folder=SimpleNamespace(path="技术标/标准文件/EW5.0"),
    )


def _index_files() -> list[dict]:
    return [{"fileId": "RAW-0001", "tierCode": "standard", "tierLabel": "标准文件", "file": {"id": "RAW-0001"}}]


def _cached_fallback(signature: str, **overrides: object) -> dict:
    payload = {
        "schemaVersion": PREVIEW_SCHEMA_VERSION,
        "signature": signature,
        "generatedAt": "2026-07-22 00:00:00",
        "status": "fallback",
        "skipReason": "LLM 不可用",
        "retryable": True,
        "preview": {"lead": "总体方案本地 TLDR", "points": ["包含章节：总体方案"], "source": "local"},
    }
    payload.update(overrides)
    return payload


class ComputeBatchPreviewRetryTests(unittest.TestCase):
    def test_llm_failure_below_limit_stays_retryable(self) -> None:
        with patch(
            "app.services.opencode_client.OpencodeClient",
            side_effect=RuntimeError("LLM 不可用"),
        ):
            out = _compute_batch_preview_payloads([_plan(llm_failures=0)])

        payload = out["RAW-0001"]
        self.assertEqual(payload["status"], "fallback")
        self.assertTrue(payload["retryable"])
        self.assertEqual(payload["llmFailures"], 1)
        # 本地 TLDR 内容仍然完整生成。
        self.assertEqual(payload["preview"]["source"], "local")
        self.assertTrue(payload["preview"]["lead"])

    def test_llm_failure_reaching_limit_marks_terminal(self) -> None:
        with patch(
            "app.services.opencode_client.OpencodeClient",
            side_effect=RuntimeError("LLM 不可用"),
        ):
            out = _compute_batch_preview_payloads([_plan(llm_failures=PREVIEW_LLM_MAX_FAILURES - 1)])

        payload = out["RAW-0001"]
        self.assertEqual(payload["status"], "fallback")
        self.assertFalse(payload["retryable"])
        self.assertEqual(payload["llmFailures"], PREVIEW_LLM_MAX_FAILURES)
        self.assertEqual(payload["preview"]["source"], "local")

    def test_missing_reply_counts_as_llm_failure(self) -> None:
        reply = json.dumps({"previews": {}}, ensure_ascii=False)
        with patch("app.services.opencode_client.OpencodeClient") as client_cls:
            client_cls._parse_json_payload = staticmethod(json.loads)
            client_cls.return_value.send_text_prompt.return_value = {"reply": reply, "modelId": "m"}
            out = _compute_batch_preview_payloads([_plan(llm_failures=PREVIEW_LLM_MAX_FAILURES - 1)])

        payload = out["RAW-0001"]
        self.assertEqual(payload["status"], "fallback")
        self.assertEqual(payload["skipReason"], "LLM 批量回复缺该文件或无效")
        self.assertFalse(payload["retryable"])
        self.assertEqual(payload["llmFailures"], PREVIEW_LLM_MAX_FAILURES)

    def test_llm_success_completes_without_failure_count(self) -> None:
        reply = json.dumps(
            {"previews": {"RAW-0001": {"lead": "AI 导读", "points": ["要点"]}}},
            ensure_ascii=False,
        )
        with patch("app.services.opencode_client.OpencodeClient") as client_cls:
            client_cls._parse_json_payload = staticmethod(json.loads)
            client_cls.return_value.send_text_prompt.return_value = {"reply": reply, "modelId": "m"}
            out = _compute_batch_preview_payloads([_plan(llm_failures=2)])

        payload = out["RAW-0001"]
        self.assertEqual(payload["status"], "completed")
        self.assertFalse(payload["retryable"])
        self.assertNotIn("llmFailures", payload)
        self.assertEqual(payload["preview"]["lead"], "AI 导读")


class BuildPreviewPlansCacheTests(unittest.IsolatedAsyncioTestCase):
    async def _build_plans(self, cached: dict | None) -> tuple[list[dict], dict]:
        with (
            patch(
                "app.models.async_session",
                return_value=_SingleExecuteSession([_raw_item(cached)]),
            ),
            patch(
                "app.services.technical_wiki_preview_generation._docx_profile_for_raw_file",
                return_value=("docx", PROFILE),
            ),
        ):
            return await _build_preview_plans(_index_files())

    async def test_terminal_fallback_cache_hit_skips_recompute(self) -> None:
        signature = _preview_signature("总体方案.docx", PROFILE, "技术标/标准文件/EW5.0")
        cached = _cached_fallback(
            signature,
            retryable=False,
            llmFailures=PREVIEW_LLM_MAX_FAILURES,
        )

        plans, stats = await self._build_plans(cached)

        self.assertEqual(stats["cached"], 1)
        self.assertEqual(len(plans), 1)
        self.assertTrue(plans[0]["hit"])
        # 缓存 payload 直接复用，不进入待算队列。
        self.assertEqual(plans[0]["payload"]["preview"]["lead"], "总体方案本地 TLDR")
        self.assertFalse(plans[0]["payload"]["retryable"])

    async def test_retryable_fallback_cache_miss_inherits_failure_count(self) -> None:
        signature = _preview_signature("总体方案.docx", PROFILE, "技术标/标准文件/EW5.0")
        cached = _cached_fallback(signature, retryable=True, llmFailures=2)

        plans, stats = await self._build_plans(cached)

        self.assertEqual(stats["cached"], 0)
        self.assertEqual(len(plans), 1)
        self.assertFalse(plans[0]["hit"])
        self.assertNotIn("payload", plans[0])
        self.assertEqual(plans[0]["llm_failures"], 2)

    async def test_legacy_cache_without_failure_count_defaults_to_zero(self) -> None:
        signature = _preview_signature("总体方案.docx", PROFILE, "技术标/标准文件/EW5.0")
        cached = _cached_fallback(signature, retryable=True)

        plans, _stats = await self._build_plans(cached)

        self.assertEqual(plans[0]["llm_failures"], 0)

    async def test_signature_change_resets_failure_count(self) -> None:
        cached = _cached_fallback("stale-signature", retryable=True, llmFailures=2)

        plans, _stats = await self._build_plans(cached)

        self.assertEqual(plans[0]["llm_failures"], 0)


class EnrichPreviewCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_enrich_skips_llm_when_terminal_fallback_cached(self) -> None:
        index_payload = {
            "tiers": [
                {
                    "name": "标准文件",
                    "tier": "standard",
                    "folders": [
                        {"name": "EW5.0", "files": [{"id": "RAW-0001", "name": "总体方案.docx"}]}
                    ],
                }
            ]
        }
        cached_payload = {
            "schemaVersion": PREVIEW_SCHEMA_VERSION,
            "signature": "sig-1",
            "generatedAt": "2026-07-22 00:00:00",
            "status": "fallback",
            "skipReason": "LLM 不可用",
            "retryable": False,
            "llmFailures": PREVIEW_LLM_MAX_FAILURES,
            "documentOutline": [],
            "preview": {"lead": "总体方案本地 TLDR", "points": ["包含章节：总体方案"], "source": "local"},
        }

        with (
            patch(
                "app.services.technical_wiki_preview_generation._build_preview_plans",
                new_callable=AsyncMock,
                return_value=(
                    [{"fileId": "RAW-0001", "hit": True, "payload": cached_payload}],
                    {"total": 1, "completed": 0, "cached": 1, "skipped": 0, "failed": 0, "errors": []},
                ),
            ),
            patch(
                "app.services.technical_wiki_preview_generation._persist_preview_payloads",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.technical_wiki_preview_generation._compute_batch_preview_payloads"
            ) as compute_payloads,
        ):
            stats = await enrich_technical_wiki_previews(index_payload)

        compute_payloads.assert_not_called()
        file_item = index_payload["tiers"][0]["folders"][0]["files"][0]
        self.assertEqual(file_item["previewStatus"], "fallback")
        self.assertFalse(file_item["previewRetryable"])
        self.assertEqual(file_item["preview"]["lead"], "总体方案本地 TLDR")
        self.assertEqual(stats["fallback"], 1)
        self.assertEqual(stats["retryable"], 0)


if __name__ == "__main__":
    unittest.main()
