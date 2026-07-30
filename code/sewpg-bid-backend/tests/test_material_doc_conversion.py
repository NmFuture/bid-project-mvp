from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from docx import Document

from app.core.config import settings


def _docx_bytes() -> bytes:
    document = Document()
    document.add_paragraph("转换后的正文")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


class _ConversionResponse:
    headers = {"content-type": "application/json"}
    text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return {"fileUrl": "http://onlyoffice/cache/result.docx"}


class _ConversionClient:
    def __init__(self, captured: dict[str, object]) -> None:
        self.captured = captured

    async def __aenter__(self) -> "_ConversionClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def post(self, url: str, *, json: dict[str, object]) -> _ConversionResponse:
        self.captured.update({"url": url, "payload": json})
        return _ConversionResponse()


class _RawFileSession:
    def __init__(self, item: SimpleNamespace) -> None:
        self.item = item

    async def __aenter__(self) -> "_RawFileSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> object:
        return SimpleNamespace(scalar_one_or_none=lambda: self.item)


class MaterialDocConversionTests(unittest.IsolatedAsyncioTestCase):
    async def test_doc_conversion_failure_updates_clean_status(self) -> None:
        from app.services import material_cleaning

        item = SimpleNamespace(
            id=1,
            name="授权书.doc",
            minio_bucket="materials",
            minio_key="raw/授权书.doc",
            version=2,
            folder=None,
        )
        status_mock = AsyncMock(
            side_effect=[
                {"cleanStatus": "cleaning"},
                {"cleanStatus": "failed", "cleanMessage": "DOC 转 DOCX 失败"},
            ]
        )
        with (
            patch.object(material_cleaning, "async_session", return_value=_RawFileSession(item)),
            patch.object(material_cleaning, "set_material_clean_status", new=status_mock),
            patch.object(
                material_cleaning,
                "_prepare_cleaning_source",
                new=AsyncMock(side_effect=RuntimeError("OnlyOffice unavailable")),
            ),
        ):
            result = await material_cleaning.clean_material_file("RAW-0001")

        self.assertEqual(result["cleanStatus"], "failed")
        self.assertEqual(status_mock.await_count, 2)
        failure_call = status_mock.await_args_list[-1]
        self.assertEqual(failure_call.args[1], "failed")
        self.assertIn("OnlyOffice unavailable", failure_call.kwargs["extra"]["cleanError"])

    async def test_doc_source_is_converted_before_cleaning(self) -> None:
        from app.services import material_cleaning

        prepare_source = getattr(material_cleaning, "_prepare_cleaning_source", None)
        self.assertIsNotNone(prepare_source, "缺少入库清洗源文件准备函数")

        async def fake_convert(**kwargs: object) -> Path:
            target = kwargs["target_path"]
            assert isinstance(target, Path)
            target.write_bytes(_docx_bytes())
            return target

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(
                material_cleaning.minio_client,
                "get_presigned_url",
                return_value="http://minio/materials/raw/授权书.doc?signature=token",
            ) as presign_mock,
            patch.object(
                material_cleaning,
                "convert_doc_to_docx",
                new=AsyncMock(side_effect=fake_convert),
            ) as convert_mock,
            patch.object(material_cleaning.minio_client, "download_file") as download_mock,
        ):
            result = await prepare_source(
                source_name="授权书.doc",
                source_bucket="materials",
                source_key="raw/授权书.doc",
                source_version=4,
                source_dir=Path(tmp),
            )

        self.assertEqual(result.name, "授权书.docx")
        presign_mock.assert_called_once_with("materials", "raw/授权书.doc", expires=1800)
        convert_mock.assert_awaited_once()
        download_mock.assert_not_called()

    async def test_onlyoffice_converts_doc_and_validates_docx(self) -> None:
        try:
            from app.services import material_doc_conversion
        except ImportError as exc:  # RED: 模块尚未实现
            self.fail(f"缺少 DOC 转换模块：{exc}")

        captured: dict[str, object] = {}

        async def fake_download(_url: str, target: Path, **_kwargs: object) -> None:
            target.write_bytes(_docx_bytes())

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(settings, "onlyoffice_internal_url", "http://onlyoffice"),
            patch.object(settings, "onlyoffice_download_allowed_hosts", ("onlyoffice",)),
            patch.object(
                material_doc_conversion.httpx,
                "AsyncClient",
                return_value=_ConversionClient(captured),
            ),
            patch.object(
                material_doc_conversion,
                "download_document_from_onlyoffice",
                new=AsyncMock(side_effect=fake_download),
            ),
        ):
            target = Path(tmp) / "授权书.docx"
            result = await material_doc_conversion.convert_doc_to_docx(
                source_url="http://minio/materials/raw/授权书.doc?signature=token",
                source_name="授权书.doc",
                source_version=3,
                target_path=target,
            )
            converted_exists = target.exists()

        self.assertEqual(result, target)
        self.assertEqual(captured["url"], "http://onlyoffice/ConvertService.ashx")
        payload = captured["payload"]
        self.assertEqual(payload["filetype"], "doc")
        self.assertEqual(payload["outputtype"], "docx")
        self.assertEqual(payload["title"], "授权书.doc")
        self.assertTrue(converted_exists)

    async def test_onlyoffice_rejects_invalid_docx_output(self) -> None:
        try:
            from app.services import material_doc_conversion
        except ImportError as exc:  # RED: 模块尚未实现
            self.fail(f"缺少 DOC 转换模块：{exc}")

        async def fake_download(_url: str, target: Path, **_kwargs: object) -> None:
            target.write_bytes(b"not-a-docx")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(settings, "onlyoffice_internal_url", "http://onlyoffice"),
            patch.object(settings, "onlyoffice_download_allowed_hosts", ("onlyoffice",)),
            patch.object(
                material_doc_conversion.httpx,
                "AsyncClient",
                return_value=_ConversionClient({}),
            ),
            patch.object(
                material_doc_conversion,
                "download_document_from_onlyoffice",
                new=AsyncMock(side_effect=fake_download),
            ),
        ):
            target = Path(tmp) / "授权书.docx"
            with self.assertRaisesRegex(RuntimeError, "有效 DOCX"):
                await material_doc_conversion.convert_doc_to_docx(
                    source_url="http://minio/materials/raw/授权书.doc?signature=token",
                    source_name="授权书.doc",
                    source_version=1,
                    target_path=target,
                )

        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
