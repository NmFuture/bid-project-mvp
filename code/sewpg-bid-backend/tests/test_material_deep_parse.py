"""素材后台深度解析（material_deep_parse）测试。

覆盖：超大 docx 后台画像解析、非 Word 原件不转换、任务队列分发与本地兜底去重。
"""

from __future__ import annotations

import io
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from docx import Document

from app.services import material_deep_parse
from app.services.job_queue import KNOWN_JOB_TYPES
from app.services.material_deep_parse import (
    deep_parse_material_file,
    deep_parse_profile_for,
    deep_parse_status_allows_enqueue,
    enqueue_deep_parse_job,
    raw_file_deep_parse_kind,
)
from app.services.technical_wiki_preview_generation import (
    _build_preview_plans,
    _docx_profile_for_raw_file,
)
from app.services.wiki_blueprint_common import MAX_SYNC_DOCX_BYTES

OVER_LIMIT = MAX_SYNC_DOCX_BYTES + 1024


def _make_docx_bytes() -> bytes:
    doc = Document()
    doc.add_paragraph("总体方案", style="Heading 1")
    doc.add_paragraph("本机组适用于低温环境，额定功率 5.0MW。")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _raw_file(name: str, *, size: int = 1024, ext_fields: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        name=name,
        size_bytes=size,
        minio_bucket="bid-materials",
        minio_key="raw/1/file",
        ext_fields=dict(ext_fields or {}),
        folder=SimpleNamespace(path="技术标/标准文件/EW5.0", tier="", bid_type=""),
    )


class DeepParseKindTests(unittest.TestCase):
    def test_pdf_xlsx_without_cleaned_are_not_deep_parsed(self) -> None:
        self.assertEqual(raw_file_deep_parse_kind("报告.pdf", {}), "")
        self.assertEqual(raw_file_deep_parse_kind("台账.xlsx", {}), "")
        self.assertEqual(raw_file_deep_parse_kind("台账.xlsm", {}), "")

    def test_oversize_docx_needs_parse(self) -> None:
        self.assertEqual(raw_file_deep_parse_kind("方案.docx", {}), "parse")

    def test_non_word_with_legacy_cleaned_output_is_not_deep_parsed(self) -> None:
        for name in ["扫描件.pdf", "台账.xlsx", "台账.xls"]:
            self.assertEqual(
                raw_file_deep_parse_kind(name, {"cleanedMinioKey": "legacy", "cleanedSize": OVER_LIMIT}),
                "",
                name,
            )

    def test_small_or_converted_material_needs_nothing(self) -> None:
        self.assertEqual(raw_file_deep_parse_kind("扫描件.pdf", {"cleanedMinioKey": "k", "cleanedSize": 1024}), "")
        self.assertEqual(raw_file_deep_parse_kind("图片.png", {}), "")

    def test_profile_only_used_when_source_key_matches(self) -> None:
        ext = {"deepParseProfile": {"sourceKey": "k1", "profile": {"headings": []}}}
        self.assertEqual(deep_parse_profile_for(ext, "k1"), {"headings": []})
        self.assertIsNone(deep_parse_profile_for(ext, "k2"))
        self.assertIsNone(deep_parse_profile_for({}, "k1"))

    def test_running_status_blocks_enqueue_until_stale(self) -> None:
        from datetime import UTC, datetime, timedelta

        fresh = {"deepParseStatus": "running", "deepParseUpdatedAt": datetime.now(UTC).isoformat()}
        stale = {
            "deepParseStatus": "running",
            "deepParseUpdatedAt": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        }
        self.assertFalse(deep_parse_status_allows_enqueue(fresh))
        self.assertTrue(deep_parse_status_allows_enqueue(stale))
        self.assertTrue(deep_parse_status_allows_enqueue({"deepParseStatus": "failed"}))
        self.assertTrue(deep_parse_status_allows_enqueue({}))


class TechnicalProfileGateTests(unittest.TestCase):
    def test_pdf_without_cleaned_stays_original_only(self) -> None:
        ext, profile = _docx_profile_for_raw_file(_raw_file("检测报告.pdf"))

        self.assertEqual(ext, "pdf")
        self.assertNotIn("deepParsePending", profile)
        self.assertIn("非 docx", profile["parseError"])

    def test_pdf_ignores_legacy_cleaned_output(self) -> None:
        ext, profile = _docx_profile_for_raw_file(
            _raw_file(
                "检测报告.pdf",
                ext_fields={"cleanedMinioKey": "legacy.pdf.docx", "cleanedSize": OVER_LIMIT},
            )
        )

        self.assertEqual(ext, "pdf")
        self.assertNotIn("deepParsePending", profile)
        self.assertIn("非 docx", profile["parseError"])

    def test_oversize_docx_marks_deep_parse_pending(self) -> None:
        ext, profile = _docx_profile_for_raw_file(_raw_file("方案.docx", size=OVER_LIMIT))

        self.assertEqual(ext, "docx")
        self.assertTrue(profile["deepParsePending"])
        self.assertIn("30MB", profile["parseError"])

    def test_deep_parse_profile_short_circuits_sync_gate(self) -> None:
        profile_data = {"headings": [{"level": 1, "title": "总体方案"}], "paragraphs": ["摘录"], "tableCount": 0}
        item = _raw_file(
            "方案.docx",
            size=OVER_LIMIT,
            ext_fields={"deepParseProfile": {"sourceKey": "raw/1/file", "profile": profile_data}},
        )

        ext, profile = _docx_profile_for_raw_file(item)

        self.assertEqual(ext, "docx")
        self.assertEqual(profile["headings"][0]["title"], "总体方案")
        self.assertEqual(profile["parseError"], "")

    def test_non_convertible_file_keeps_empty_profile(self) -> None:
        ext, profile = _docx_profile_for_raw_file(_raw_file("现场照片.png"))

        self.assertEqual(ext, "png")
        self.assertNotIn("deepParsePending", profile)


class _SingleExecuteSession:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    async def __aenter__(self) -> "_SingleExecuteSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> object:
        items = self._items

        class _Result:
            def scalars(self) -> "_Result":
                return self

            def all(self) -> list[object]:
                return list(items)

        return _Result()


class BuildPreviewPlansDeepParseTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_material_enqueues_and_stays_retryable(self) -> None:
        raw = _raw_file("检测报告.pdf")
        empty_profile = {
            "headings": [],
            "bodyHeadings": [],
            "paragraphs": [],
            "tables": [],
            "tableCount": 0,
            "parseError": "",
            "deepParsePending": True,
        }
        with (
            patch("app.models.async_session", return_value=_SingleExecuteSession([raw])),
            patch(
                "app.services.technical_wiki_preview_generation._docx_profile_for_raw_file",
                return_value=("pdf", empty_profile),
            ),
            patch(
                "app.services.technical_wiki_preview_generation.enqueue_deep_parse_job",
            ) as enqueue_mock,
        ):
            plans, stats = await _build_preview_plans(
                [{"fileId": "RAW-0001", "tierCode": "standard", "tierLabel": "标准文件", "file": {"id": "RAW-0001"}}]
            )

        self.assertEqual(stats["skipped"], 1)
        payload = plans[0]["payload"]
        self.assertEqual(payload["status"], "fallback")
        self.assertTrue(payload["retryable"])
        self.assertIn("后台深度解析", payload["skipReason"])
        enqueue_mock.assert_called_once_with("RAW-0001")

    async def test_non_pending_skip_stays_terminal(self) -> None:
        raw = _raw_file("现场照片.png")
        empty_profile = {
            "headings": [],
            "bodyHeadings": [],
            "paragraphs": [],
            "tables": [],
            "tableCount": 0,
            "parseError": "",
        }
        with (
            patch("app.models.async_session", return_value=_SingleExecuteSession([raw])),
            patch(
                "app.services.technical_wiki_preview_generation._docx_profile_for_raw_file",
                return_value=("png", empty_profile),
            ),
            patch(
                "app.services.technical_wiki_preview_generation.enqueue_deep_parse_job",
            ) as enqueue_mock,
        ):
            plans, _stats = await _build_preview_plans(
                [{"fileId": "RAW-0001", "tierCode": "standard", "tierLabel": "标准文件", "file": {"id": "RAW-0001"}}]
            )

        self.assertFalse(plans[0]["payload"]["retryable"])
        enqueue_mock.assert_not_called()


class BusinessProfileGateTests(unittest.TestCase):
    def _profile(self, item: SimpleNamespace) -> dict:
        from app.services.business_wiki_generation import _profile_raw_file

        return _profile_raw_file(item)

    def test_oversize_docx_enqueues_deep_parse(self) -> None:
        with patch("app.services.business_wiki_generation.enqueue_deep_parse_job") as enqueue_mock:
            profile = self._profile(_raw_file("合同.docx", size=OVER_LIMIT))

        self.assertTrue(profile["deepParsePending"])
        self.assertIn("后台深度解析", profile["parseError"])
        enqueue_mock.assert_called_once_with("RAW-0001")

    def test_xlsx_does_not_enqueue_background_convert(self) -> None:
        with patch("app.services.business_wiki_generation.enqueue_deep_parse_job") as enqueue_mock:
            profile = self._profile(_raw_file("价格表.xlsx"))

        self.assertNotIn("deepParsePending", profile)
        enqueue_mock.assert_not_called()

    def test_xlsx_ignores_legacy_cleaned_output(self) -> None:
        item = _raw_file(
            "价格表.xlsx",
            ext_fields={"cleanedMinioKey": "legacy.xlsx.docx", "cleanedSize": OVER_LIMIT},
        )
        with patch("app.services.business_wiki_generation.enqueue_deep_parse_job") as enqueue_mock:
            profile = self._profile(item)

        self.assertEqual(profile["ext"], "xlsx")
        self.assertFalse(profile["hasCleanedWord"])
        self.assertNotIn("deepParsePending", profile)
        enqueue_mock.assert_not_called()

    def test_deep_parse_profile_used_directly(self) -> None:
        profile_data = {"headings": [{"level": 1, "title": "资质"}], "paragraphs": [], "tableCount": 0}
        item = _raw_file(
            "合同.docx",
            size=OVER_LIMIT,
            ext_fields={"deepParseProfile": {"sourceKey": "raw/1/file", "profile": profile_data}},
        )
        with patch("app.services.business_wiki_generation.enqueue_deep_parse_job") as enqueue_mock:
            profile = self._profile(item)

        self.assertEqual(profile["headings"][0]["title"], "资质")
        self.assertEqual(profile["parseError"], "")
        enqueue_mock.assert_not_called()


class BusinessOcrGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_pdf_source_ignores_fresh_legacy_ocr_cache(self) -> None:
        from app.services import business_wiki_generation

        signature = {
            "version": 1,
            "sourceMinioKey": "raw/1/report.pdf",
            "sourceSizeBytes": 1024,
            "cleanedMinioKey": "",
            "cleanedSize": 0,
        }
        item = SimpleNamespace(
            id=1,
            name="检测报告.pdf",
            version=1,
            size_bytes=1024,
            minio_bucket="bid-materials",
            minio_key="raw/1/report.pdf",
            ext_fields={
                "businessWikiOcr": {
                    "schemaVersion": business_wiki_generation.BUSINESS_WIKI_OCR_VERSION,
                    "signature": signature,
                    "status": "completed",
                    "sourceType": "source_file",
                    "text": "历史 PDF OCR 文本",
                }
            },
        )

        payload = await business_wiki_generation._ensure_business_wiki_ocr_cache(
            item,
            {"sourceExt": "pdf", "ext": "pdf"},
        )

        self.assertEqual(payload["status"], "not_required")
        self.assertEqual(payload["text"], "")

    async def test_pdf_source_does_not_trigger_business_wiki_ocr(self) -> None:
        from app.services import business_wiki_generation

        item = SimpleNamespace(
            id=1,
            name="检测报告.pdf",
            version=1,
            size_bytes=1024,
            minio_bucket="bid-materials",
            minio_key="raw/1/report.pdf",
            ext_fields={},
        )
        with patch.object(
            business_wiki_generation,
            "_recognize_source_file_for_wiki",
            new=AsyncMock(return_value={"status": "completed", "text": "不应读取"}),
        ) as recognize_mock:
            payload = await business_wiki_generation._ensure_business_wiki_ocr_cache(
                item,
                {"sourceExt": "pdf", "ext": "pdf"},
            )

        self.assertEqual(payload["status"], "not_required")
        recognize_mock.assert_not_awaited()


class _DeepParseSession:
    def __init__(self, item: SimpleNamespace) -> None:
        self._item = item

    async def __aenter__(self) -> "_DeepParseSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> object:
        item = self._item
        return SimpleNamespace(scalar_one_or_none=lambda: item)

    async def get(self, _model: object, _pk: object) -> SimpleNamespace:
        return self._item

    async def commit(self) -> None:
        return None


class DeepParseMaterialFileTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversize_docx_writes_profile(self) -> None:
        item = _raw_file("方案.docx", size=OVER_LIMIT)
        docx_bytes = _make_docx_bytes()
        with (
            patch("app.services.material_deep_parse.async_session", return_value=_DeepParseSession(item)),
            patch("app.services.material_deep_parse.minio_client") as minio_mock,
        ):
            minio_mock.get_object.return_value = docx_bytes
            result = await deep_parse_material_file("RAW-0001")

        self.assertEqual(result["deepParseStatus"], "parsed")
        profile = item.ext_fields["deepParseProfile"]
        self.assertEqual(profile["sourceKey"], "raw/1/file")
        self.assertEqual(profile["profile"]["headings"][0]["title"], "总体方案")
        self.assertEqual(item.ext_fields["deepParseStatus"], "parsed")

    async def test_pdf_is_not_converted_by_deep_parse(self) -> None:
        item = _raw_file("检测报告.pdf")
        with patch("app.services.material_deep_parse.async_session", return_value=_DeepParseSession(item)):
            result = await deep_parse_material_file("RAW-0001")

        self.assertEqual(result["deepParseStatus"], "failed")
        self.assertIn("不支持", result["deepParseMessage"])

    async def test_pdf_with_legacy_cleaned_output_is_not_parsed(self) -> None:
        item = _raw_file(
            "检测报告.pdf",
            ext_fields={
                "cleanedMinioKey": "legacy.pdf.docx",
                "cleanedMinioBucket": "bid-materials",
                "cleanedSize": OVER_LIMIT,
            },
        )
        with (
            patch("app.services.material_deep_parse.async_session", return_value=_DeepParseSession(item)),
            patch("app.services.material_deep_parse.minio_client") as minio_mock,
        ):
            result = await deep_parse_material_file("RAW-0001")

        self.assertEqual(result["deepParseStatus"], "failed")
        self.assertIn("不支持", result["deepParseMessage"])
        minio_mock.get_object.assert_not_called()

    async def test_unsupported_type_fails_explicitly(self) -> None:
        item = _raw_file("现场照片.png")
        with patch("app.services.material_deep_parse.async_session", return_value=_DeepParseSession(item)):
            result = await deep_parse_material_file("RAW-0001")

        self.assertEqual(result["deepParseStatus"], "failed")
        self.assertEqual(item.ext_fields["deepParseStatus"], "failed")


class EnqueueAndWorkerTests(unittest.TestCase):
    def test_job_type_registered(self) -> None:
        self.assertIn("material_deep_parse", KNOWN_JOB_TYPES)

    def test_local_fallback_when_redis_unavailable_and_deduped(self) -> None:
        material_deep_parse._local_inflight.clear()
        with (
            patch(
                "app.services.material_deep_parse.enqueue_generation_job",
                side_effect=RuntimeError("redis down"),
            ),
            patch("app.services.material_deep_parse.submit_local_job") as local_mock,
        ):
            first = enqueue_deep_parse_job("RAW-0001")
            second = enqueue_deep_parse_job("RAW-0001")

        self.assertTrue(first["queued"])
        self.assertTrue(first["local"])
        self.assertTrue(second["deduped"])
        local_mock.assert_called_once()
        material_deep_parse._local_inflight.clear()

    def test_worker_dispatches_deep_parse_job(self) -> None:
        from app.workers import redis_worker

        with patch(
            "app.services.material_deep_parse.deep_parse_material_file_sync",
            return_value={"deepParseStatus": "parsed", "deepParseMessage": "ok"},
        ) as runner_mock, patch(
            "app.workers.redis_worker.renew_generation_lock",
            return_value=True,
        ):
            redis_worker._run_job(
                {"id": "job-1", "type": "material_deep_parse", "projectId": "RAW-0001", "data": {"fileId": "RAW-0001"}}
            )

        runner_mock.assert_called_once_with("RAW-0001", {"fileId": "RAW-0001"})


if __name__ == "__main__":
    unittest.main()
