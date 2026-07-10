"""技术标 AI 填写 PDF 素材 OCR sidecar 生成单测。

F 系列认证表金标 0% 的后端一环：PDF 素材此前在下载门槛就被拒绝，
从未落地也从未 OCR。本组测试覆盖 _ensure_pdf_ocr_sidecar 的
生成/缓存复用/未配置跳过/失败透出四种状态，OCR 服务全部 mock，
不依赖外部模型。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import technical_gap_ai_fill as ai_fill
from app.services.peripheral import PeripheralError


class EnsurePdfOcrSidecarTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.pdf_path = Path(self._tmp.name) / "MAT-9-型式认证证书.pdf"
        self.pdf_path.write_bytes(b"%PDF-1.4 fake")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_generates_sidecar_from_ocr_text(self) -> None:
        async def fake_ocr(**_kwargs):
            return "证书编号：TC-001\n有效期至 2030年1月1日", {"status": "completed"}

        with patch.object(ai_fill.ocr_service, "recognize_text_for_parse", side_effect=fake_ocr):
            sidecar, status = ai_fill._ensure_pdf_ocr_sidecar(self.pdf_path)
        self.assertEqual(status, "generated")
        self.assertTrue(Path(sidecar).exists())
        self.assertIn("TC-001", Path(sidecar).read_text(encoding="utf-8"))

    def test_reuses_cached_sidecar_without_calling_ocr(self) -> None:
        cached = self.pdf_path.with_suffix(".ocr.txt")
        cached.write_text("已缓存文本", encoding="utf-8")

        async def must_not_call(**_kwargs):
            raise AssertionError("缓存命中时不应调用 OCR")

        with patch.object(ai_fill.ocr_service, "recognize_text_for_parse", side_effect=must_not_call):
            sidecar, status = ai_fill._ensure_pdf_ocr_sidecar(self.pdf_path)
        self.assertEqual(status, "cached")
        self.assertEqual(sidecar, str(cached))

    def test_config_missing_returns_skipped(self) -> None:
        async def config_required(**_kwargs):
            raise PeripheralError(400, "请先在系统设置中启用并配置 OCR 模型。", "OCR_CONFIG_REQUIRED")

        with patch.object(ai_fill.ocr_service, "recognize_text_for_parse", side_effect=config_required):
            sidecar, status = ai_fill._ensure_pdf_ocr_sidecar(self.pdf_path)
        self.assertEqual(sidecar, "")
        self.assertTrue(status.startswith("skipped"))
        self.assertFalse(self.pdf_path.with_suffix(".ocr.txt").exists())

    def test_ocr_failure_surfaces_reason(self) -> None:
        async def boom(**_kwargs):
            raise RuntimeError("模型超时")

        with patch.object(ai_fill.ocr_service, "recognize_text_for_parse", side_effect=boom):
            sidecar, status = ai_fill._ensure_pdf_ocr_sidecar(self.pdf_path)
        self.assertEqual(sidecar, "")
        self.assertIn("模型超时", status)

    def test_empty_ocr_text_is_failure(self) -> None:
        async def empty(**_kwargs):
            return "   ", {"status": "completed"}

        with patch.object(ai_fill.ocr_service, "recognize_text_for_parse", side_effect=empty):
            sidecar, status = ai_fill._ensure_pdf_ocr_sidecar(self.pdf_path)
        self.assertEqual(sidecar, "")
        self.assertTrue(status.startswith("failed"))


if __name__ == "__main__":
    unittest.main()
