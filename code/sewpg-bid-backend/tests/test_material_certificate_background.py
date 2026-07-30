"""证书台账后台任务：事件循环不阻塞（R06-B05-02）与 CAS 并发保护（R06-B05-03）。

用内存 fake 替代 async_session / _load_raw_files / MinIO，不依赖外部服务。
"""
from __future__ import annotations

import asyncio
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app.services.material_certificate_time as mct


_CERT_TEXT = """
风能产品符合证明
证书编号：CQC250304413272200
发证日期：2025 年 04 月 10 日
有效期至：2027 年 04 月 09 日
"""

_FAILED_META = {
    "issueDate": "",
    "expiryDate": "",
    "status": "failed",
    "source": "pdf_text",
    "updatedAt": "2026-01-01T00:00:00+00:00",
    "errorMessage": "之前识别失败",
}

_MANUAL_META = {
    "issueDate": "2025-01-01",
    "expiryDate": "2027-01-01",
    "status": "manual",
    "source": "manual",
    "updatedAt": "2026-06-01T00:00:00+00:00",
    "errorMessage": "",
}


class _FakeSession:
    """最小 async session：只支持 batch 提交路径用到的 get / commit。"""

    def __init__(self, store: dict[int, SimpleNamespace]) -> None:
        self._store = store

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, model: object, ident: int) -> SimpleNamespace | None:
        return self._store.get(int(ident))

    async def commit(self) -> None:
        pass


class CertificateBackgroundTestBase(unittest.IsolatedAsyncioTestCase):
    """公共 fake：内存行存储 + 会话/加载/MinIO/解析桩。"""

    def _make_row(self, name: str, meta: dict | None) -> SimpleNamespace:
        ext = {"certificateMeta": dict(meta)} if meta else {}
        return SimpleNamespace(name=name, folder_path="技术标/证书", ext_fields=ext)

    def _install_fakes(self, store: dict[int, SimpleNamespace]) -> None:
        self.store = store

        async def fake_load(*, bid_type: str, folder_path: str = "", file_ids: list[str] | None = None):
            wanted = {mct._raw_file_numeric_id(value) for value in file_ids} if file_ids else None
            items = []
            for file_id, row in self.store.items():
                if wanted is not None and file_id not in wanted:
                    continue
                # ext_fields 浅拷贝模拟“加载时刻”的行快照，之后的用户操作不影响已加载 item
                items.append(SimpleNamespace(
                    id=file_id,
                    name=row.name,
                    folder=SimpleNamespace(path=row.folder_path),
                    ext_fields=dict(row.ext_fields),
                    minio_bucket="bucket",
                    minio_key=f"key-{file_id}",
                    mime_type="application/pdf",
                ))
            return items

        async def fake_ensure_tables(session: object) -> None:
            pass

        def fast_get_object(bucket: str, key: str) -> bytes:
            return b"pdf-bytes"

        patches = [
            patch.object(mct, "_load_raw_files", side_effect=fake_load),
            patch.object(mct, "async_session", side_effect=lambda: _FakeSession(self.store)),
            patch.object(mct, "ensure_material_runtime_tables", side_effect=fake_ensure_tables),
            patch.object(mct.minio_client, "get_object", side_effect=fast_get_object),
            patch.object(
                mct,
                "_extract_text_without_ocr",
                side_effect=lambda name, content: (_CERT_TEXT, {"source": "pdf_text"}),
            ),
            patch.object(mct, "_configured_scope_paths", return_value=["技术标/证书"]),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)


class CertificateEventLoopSafetyTests(CertificateBackgroundTestBase):
    """R06-B05-02：同步下载/解析必须在事件循环外执行。"""

    async def test_batch_does_not_block_event_loop_during_sync_download(self) -> None:
        self._install_fakes({1: self._make_row("证书A.pdf", None)})

        def slow_get_object(bucket: str, key: str) -> bytes:
            time.sleep(0.4)  # 真同步阻塞：若在事件循环内执行会卡住所有请求
            return b"pdf-bytes"

        with patch.object(mct.minio_client, "get_object", side_effect=slow_get_object):
            gaps: list[float] = []

            async def ticker() -> None:
                last = time.perf_counter()
                while True:
                    await asyncio.sleep(0.01)
                    now = time.perf_counter()
                    gaps.append(now - last)
                    last = now

            tick_task = asyncio.create_task(ticker())
            try:
                await mct.run_certificate_time_batch(bid_type="technical", file_ids=["1"], limit=1)
            finally:
                tick_task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await tick_task

        self.assertTrue(gaps, "ticker 应在批任务期间持续运行")
        self.assertLess(max(gaps), 0.2, f"事件循环被阻塞，最大 tick 间隔 {max(gaps):.3f}s")

    async def test_batch_does_not_block_event_loop_during_sync_parse(self) -> None:
        self._install_fakes({1: self._make_row("证书A.pdf", None)})

        def slow_parse(name: str, content: bytes):
            time.sleep(0.4)
            return _CERT_TEXT, {"source": "pdf_text"}

        with patch.object(mct, "_extract_text_without_ocr", side_effect=slow_parse):
            gaps: list[float] = []

            async def ticker() -> None:
                last = time.perf_counter()
                while True:
                    await asyncio.sleep(0.01)
                    now = time.perf_counter()
                    gaps.append(now - last)
                    last = now

            tick_task = asyncio.create_task(ticker())
            try:
                await mct.run_certificate_time_batch(bid_type="technical", file_ids=["1"], limit=1)
            finally:
                tick_task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await tick_task

        self.assertLess(max(gaps), 0.2, f"事件循环被阻塞，最大 tick 间隔 {max(gaps):.3f}s")


class CertificateCasConflictTests(CertificateBackgroundTestBase):
    """R06-B05-03：任务选入后发生人工操作/并发写入时，后台写入必须跳过并报冲突。"""

    async def test_incremental_skips_file_edited_manually_after_selection(self) -> None:
        row = self._make_row("证书A.pdf", _FAILED_META)
        self._install_fakes({1: row})

        def get_object_with_user_edit(bucket: str, key: str) -> bytes:
            # 任务已选入该文件、处理到它之前，用户人工保存 status=manual
            row.ext_fields = {"certificateMeta": dict(_MANUAL_META)}
            return b"pdf-bytes"

        with patch.object(mct.minio_client, "get_object", side_effect=get_object_with_user_edit):
            result = await mct.run_certificate_time_incremental(bid_type="technical")

        self.assertEqual(result["conflicted"], [{"fileId": "RAW-0001", "name": "证书A.pdf", "reason": "modified"}])
        self.assertEqual(result["items"][0]["status"], "conflicted")
        # 人工确认值不被自动结果覆盖
        self.assertEqual(row.ext_fields["certificateMeta"], _MANUAL_META)
        self.assertIn("冲突跳过 1 个", result["message"])

    async def test_incremental_skips_file_deleted_after_selection(self) -> None:
        row = self._make_row("证书A.pdf", _FAILED_META)
        self._install_fakes({1: row})

        def get_object_with_user_delete(bucket: str, key: str) -> bytes:
            # 任务已选入该文件、处理到它之前，用户删除台账记录（摘掉 certificateMeta）
            row.ext_fields.pop("certificateMeta", None)
            return b"pdf-bytes"

        with patch.object(mct.minio_client, "get_object", side_effect=get_object_with_user_delete):
            result = await mct.run_certificate_time_incremental(bid_type="technical")

        self.assertEqual(result["conflicted"], [{"fileId": "RAW-0001", "name": "证书A.pdf", "reason": "deleted"}])
        # 已删除记录不重新出现
        self.assertNotIn("certificateMeta", row.ext_fields)

    async def test_concurrent_recognize_tasks_do_not_overwrite_each_other(self) -> None:
        row = self._make_row("证书A.pdf", _FAILED_META)
        self._install_fakes({1: row})

        # 构造确定性的真并发时序：两个任务都完成选入快照之后才放行解析，
        # 先提交者胜，后提交者必须冲突而不是覆盖。
        # get_object 桩只阻塞 worker 线程（不阻塞事件循环），与协程调度顺序无关。
        both_loaded = threading.Event()
        load_calls = 0
        installed_load = mct._load_raw_files  # _install_fakes 已替换为内存桩

        async def counting_load(**kwargs: object) -> list:
            nonlocal load_calls
            load_calls += 1
            if load_calls >= 2:
                both_loaded.set()
            return await installed_load(**kwargs)

        def barrier_get_object(bucket: str, key: str) -> bytes:
            self.assertTrue(both_loaded.wait(timeout=5), "两个并发任务都应先完成选入快照")
            return b"pdf-bytes"

        with (
            patch.object(mct, "_load_raw_files", side_effect=counting_load),
            patch.object(mct.minio_client, "get_object", side_effect=barrier_get_object),
        ):
            results = await asyncio.gather(
                mct.run_certificate_time_batch(bid_type="technical", file_ids=["1"], limit=1),
                mct.run_certificate_time_batch(bid_type="technical", file_ids=["1"], limit=1),
            )

        statuses = sorted(item["items"][0]["status"] for item in results)
        self.assertEqual(statuses, ["conflicted", "extracted"])
        conflicted = [item for item in results if item["conflicted"]]
        self.assertEqual(len(conflicted), 1)
        self.assertEqual(conflicted[0]["conflicted"][0]["reason"], "modified")
        # 最终保留先提交者的识别结果
        self.assertEqual(row.ext_fields["certificateMeta"]["status"], "extracted")
        self.assertEqual(row.ext_fields["certificateMeta"]["issueDate"], "2025-04-10")

    async def test_batch_writes_normally_without_concurrent_changes(self) -> None:
        row = self._make_row("证书A.pdf", _FAILED_META)
        self._install_fakes({1: row})

        result = await mct.run_certificate_time_batch(bid_type="technical", file_ids=["1"], limit=1)

        self.assertEqual(result["conflicted"], [])
        self.assertEqual(result["items"][0]["status"], "extracted")
        self.assertEqual(row.ext_fields["certificateMeta"]["expiryDate"], "2027-04-09")


if __name__ == "__main__":
    unittest.main()
