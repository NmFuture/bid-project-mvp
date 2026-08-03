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


class PrepareFillMaterialsWithOcrTests(unittest.TestCase):
    """填表任务内部 OCR 循环补齐：循环到无配额跳过 / 零进展停止 / 轮数兜底。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.work_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _items(count: int) -> list[dict]:
        return [{"id": f"MAT-{i}", "fileName": f"mat{i}.pdf"} for i in range(count)]

    def _fake_prepare(self, per_call_budget: int):
        calls = {"count": 0}

        def fake(materials, work_dir, *, cache_dir=None, limit=240, ocr_pdf=False, ocr_budget=12):
            calls["count"] += 1
            remaining = per_call_budget
            prepared = []
            for item in materials:
                item = dict(item)
                if item.get("ocrTextPath"):
                    item["ocrStatus"] = "cached"
                elif remaining > 0:
                    remaining -= 1
                    item["ocrTextPath"] = str(self.work_dir / f"{item['id']}.ocr.txt")
                    item["ocrStatus"] = "generated"
                else:
                    item["ocrStatus"] = ai_fill._OCR_BUDGET_SKIPPED_STATUS
                prepared.append(item)
            return prepared

        return fake, calls

    def test_loops_until_no_quota_skipped(self) -> None:
        fake, calls = self._fake_prepare(per_call_budget=2)
        with patch.object(ai_fill, "_prepare_material_index_files", side_effect=fake):
            material_index, _refs, _recs = ai_fill._prepare_fill_materials_with_ocr(
                self._items(3), [], [], self.work_dir, cache_dir=self.work_dir
            )
        # 第 1 轮就绪 2 份余 1 份跳过，第 2 轮补齐后退出：2 轮 × 3 路 = 6 次调用
        self.assertEqual(calls["count"], 6)
        self.assertTrue(all(item.get("ocrTextPath") for item in material_index))

    def test_stops_when_no_progress(self) -> None:
        fake, calls = self._fake_prepare(per_call_budget=0)
        with patch.object(ai_fill, "_prepare_material_index_files", side_effect=fake):
            material_index, _refs, _recs = ai_fill._prepare_fill_materials_with_ocr(
                self._items(3), [], [], self.work_dir, cache_dir=self.work_dir
            )
        # 首轮 ready=0 > -1 继续，次轮零进展（0 <= 0）停止，避免死循环
        self.assertEqual(calls["count"], 6)
        self.assertTrue(all(not item.get("ocrTextPath") for item in material_index))

    def test_respects_max_rounds(self) -> None:
        fake, calls = self._fake_prepare(per_call_budget=1)
        with patch.object(ai_fill, "_prepare_material_index_files", side_effect=fake):
            ai_fill._prepare_fill_materials_with_ocr(
                self._items(ai_fill._AI_FILL_OCR_PREP_MAX_ROUNDS + 5),
                [],
                [],
                self.work_dir,
                cache_dir=self.work_dir,
            )
        # 每轮都有进展但都补不完，触达兜底轮数上限退出
        self.assertEqual(calls["count"], ai_fill._AI_FILL_OCR_PREP_MAX_ROUNDS * 3)


if __name__ == "__main__":
    unittest.main()
