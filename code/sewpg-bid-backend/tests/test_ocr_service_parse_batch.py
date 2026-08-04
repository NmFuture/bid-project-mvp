"""OcrService.recognize_texts_for_parse_batch 批量提交并发等待单测。

R09-B07-01：parse 用途 OCR 从逐份"提交+同步等待"改为"批量提交全部
OcrTask 后 asyncio.gather 统一等待"。本组测试 mock 掉配置检查、任务
登记与结果等待，验证：全部任务一次性提交、等待阶段真并发、结果按提交
顺序回填、单份失败不影响其他份、未配置整体抛出 OCR_CONFIG_REQUIRED。
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.services.ocr_service import ocr_service
from app.services.peripheral import PeripheralError


class RecognizeTextsForParseBatchTests(unittest.IsolatedAsyncioTestCase):
    def _patches(self, wait_side_effect, submit_side_effect=None):
        async def fake_submit(*, file_name, content, mime_type=""):
            if submit_side_effect is not None:
                return submit_side_effect(file_name=file_name, content=content, mime_type=mime_type)
            return f"task-{file_name}"

        async def fake_config():
            return None

        async def fake_start_worker():
            return None

        return [
            patch.object(ocr_service, "_require_parse_ocr_config", side_effect=fake_config),
            patch.object(ocr_service, "_submit_parse_task", side_effect=fake_submit),
            patch.object(ocr_service, "start_worker", side_effect=fake_start_worker),
            patch.object(ocr_service, "_await_parse_task_result", side_effect=wait_side_effect),
        ]

    async def test_waits_run_concurrently_and_results_keep_order(self) -> None:
        state = {"inflight": 0, "max_inflight": 0}

        async def fake_wait(task_id):
            state["inflight"] += 1
            state["max_inflight"] = max(state["max_inflight"], state["inflight"])
            await asyncio.sleep(0.02)
            state["inflight"] -= 1
            return f"text-{task_id}", {"status": "completed"}

        patches = self._patches(fake_wait)
        for p in patches:
            p.start()
        try:
            results = await ocr_service.recognize_texts_for_parse_batch(
                files=[(f"f{i}.pdf", b"%PDF", "application/pdf") for i in range(5)]
            )
        finally:
            for p in patches:
                p.stop()
        # 5 份统一 gather 等待，等待阶段并发 > 1（串行时恒为 1）
        self.assertGreater(state["max_inflight"], 1)
        self.assertEqual(
            [text for text, _meta in results],
            [f"text-task-f{i}.pdf" for i in range(5)],
        )

    async def test_single_failure_does_not_block_others(self) -> None:
        async def fake_wait(task_id):
            if task_id == "task-bad.pdf":
                raise PeripheralError(500, "OCR 识别失败：模型超时", "OCR_TASK_FAILED")
            return f"text-{task_id}", {"status": "completed"}

        patches = self._patches(fake_wait)
        for p in patches:
            p.start()
        try:
            results = await ocr_service.recognize_texts_for_parse_batch(
                files=[("ok1.pdf", b"%PDF", "application/pdf"), ("bad.pdf", b"%PDF", "application/pdf"), ("ok2.pdf", b"%PDF", "application/pdf")]
            )
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(results[0][0], "text-task-ok1.pdf")
        self.assertIsInstance(results[1], PeripheralError)
        self.assertEqual(results[1].code, "OCR_TASK_FAILED")
        self.assertEqual(results[2][0], "text-task-ok2.pdf")

    async def test_invalid_file_type_lands_in_results_without_blocking(self) -> None:
        async def fake_wait(task_id):
            return f"text-{task_id}", {"status": "completed"}

        def submit_side_effect(*, file_name, content, mime_type=""):
            if file_name.endswith(".docx"):
                raise PeripheralError(400, "OCR 仅支持图片或图片型 PDF。", "OCR_FILE_TYPE_INVALID")
            return f"task-{file_name}"

        patches = self._patches(fake_wait, submit_side_effect=submit_side_effect)
        for p in patches:
            p.start()
        try:
            results = await ocr_service.recognize_texts_for_parse_batch(
                files=[("a.pdf", b"%PDF", "application/pdf"), ("b.docx", b"doc", "")]
            )
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(results[0][0], "text-task-a.pdf")
        self.assertIsInstance(results[1], PeripheralError)
        self.assertEqual(results[1].code, "OCR_FILE_TYPE_INVALID")

    async def test_config_missing_raises_for_whole_batch(self) -> None:
        async def config_required():
            raise PeripheralError(400, "请先在系统设置中启用并配置 OCR 模型。", "OCR_CONFIG_REQUIRED")

        async def must_not_submit(**_kwargs):
            raise AssertionError("OCR 未配置时不应提交任务")

        async def fake_wait(task_id):
            return "", {}

        with (
            patch.object(ocr_service, "_require_parse_ocr_config", side_effect=config_required),
            patch.object(ocr_service, "_submit_parse_task", side_effect=must_not_submit),
            patch.object(ocr_service, "_await_parse_task_result", side_effect=fake_wait),
        ):
            with self.assertRaises(PeripheralError) as ctx:
                await ocr_service.recognize_texts_for_parse_batch(
                    files=[("a.pdf", b"%PDF", "application/pdf")]
                )
        self.assertEqual(ctx.exception.code, "OCR_CONFIG_REQUIRED")


if __name__ == "__main__":
    unittest.main()
