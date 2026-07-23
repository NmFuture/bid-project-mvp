"""S7 素材来源回归：普通 matchedMaterials 优先组装原始 Word，不优先用清洗版。

背景（1.9 层级误升格）：素材清洗版可能把正文短句误升为 Heading，S7 只认
原始 docx 的真实 Heading/outlineLvl/TOC；原始文件缺失或不是 docx 时才回退
清洗稿。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.services import tech_assembly
from app.services import technical_gap_actions

DOCX_PAYLOAD = {
    "bucket": "raw",
    "key": "original.docx",
    "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "fileName": "原始.docx",
}
CLEANED_PAYLOAD = {
    "bucket": "raw",
    "key": "cleaned.docx",
    "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "fileName": "清洗版.docx",
}
DOC_PAYLOAD = {
    "bucket": "raw",
    "key": "original.doc",
    "mimeType": "application/msword",
    "fileName": "原始.doc",
}


class CopyMaterialToLibraryTests(unittest.TestCase):
    def test_prefers_original_word_over_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.docx"
            with patch.object(
                tech_assembly.technical_material_store,
                "raw_download_content",
                new=AsyncMock(return_value=dict(DOCX_PAYLOAD)),
            ) as raw_mock, patch.object(
                tech_assembly.technical_material_store,
                "raw_download_cleaned_content",
                new=AsyncMock(return_value=dict(CLEANED_PAYLOAD)),
            ) as cleaned_mock, patch.object(
                tech_assembly.minio_client, "download_file"
            ) as download_mock:
                tech_assembly._copy_material_to_library("RAW-0001", "", target)

            raw_mock.assert_awaited_once()
            cleaned_mock.assert_not_awaited()
            download_mock.assert_called_once_with("raw", "original.docx", target)

    def test_falls_back_to_cleaned_when_original_not_docx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.docx"
            with patch.object(
                tech_assembly.technical_material_store,
                "raw_download_content",
                new=AsyncMock(return_value=dict(DOC_PAYLOAD)),
            ), patch.object(
                tech_assembly.technical_material_store,
                "raw_download_cleaned_content",
                new=AsyncMock(return_value=dict(CLEANED_PAYLOAD)),
            ) as cleaned_mock, patch.object(
                tech_assembly.minio_client, "download_file"
            ) as download_mock:
                tech_assembly._copy_material_to_library("RAW-0001", "", target)

            cleaned_mock.assert_awaited_once()
            download_mock.assert_called_once_with("raw", "cleaned.docx", target)

    def test_falls_back_to_cleaned_when_original_download_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.docx"
            with patch.object(
                tech_assembly.technical_material_store,
                "raw_download_content",
                new=AsyncMock(side_effect=RuntimeError("missing")),
            ), patch.object(
                tech_assembly.technical_material_store,
                "raw_download_cleaned_content",
                new=AsyncMock(return_value=dict(CLEANED_PAYLOAD)),
            ) as cleaned_mock, patch.object(
                tech_assembly.minio_client, "download_file"
            ) as download_mock:
                tech_assembly._copy_material_to_library("RAW-0001", "", target)

            cleaned_mock.assert_awaited_once()
            download_mock.assert_called_once_with("raw", "cleaned.docx", target)


class DownloadableGapMaterialPayloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_prefers_original_word_over_cleaned(self) -> None:
        with patch.object(
            technical_gap_actions.technical_material_store,
            "raw_download_content",
            new=AsyncMock(return_value=dict(DOCX_PAYLOAD)),
        ), patch.object(
            technical_gap_actions.technical_material_store,
            "raw_download_cleaned_content",
            new=AsyncMock(return_value=dict(CLEANED_PAYLOAD)),
        ) as cleaned_mock:
            payload, source_kind = await technical_gap_actions._downloadable_technical_material_payload("RAW-0001")

        self.assertEqual(source_kind, "raw")
        self.assertEqual(payload["key"], "original.docx")
        cleaned_mock.assert_not_awaited()

    async def test_falls_back_to_cleaned_when_original_not_docx(self) -> None:
        with patch.object(
            technical_gap_actions.technical_material_store,
            "raw_download_content",
            new=AsyncMock(return_value=dict(DOC_PAYLOAD)),
        ), patch.object(
            technical_gap_actions.technical_material_store,
            "raw_download_cleaned_content",
            new=AsyncMock(return_value=dict(CLEANED_PAYLOAD)),
        ):
            payload, source_kind = await technical_gap_actions._downloadable_technical_material_payload("RAW-0001")

        self.assertEqual(source_kind, "cleaned")
        self.assertEqual(payload["key"], "cleaned.docx")


if __name__ == "__main__":
    unittest.main()
