"""技术标附表 AI 填写（LLM 判断为唯一模式）后端接线单测。

覆盖：
1. 始终走 LLM 模式：prompt 走 prepare→plan→apply 流程，不传 early_tool_command
   （等会话自然结束），OpencodeClient 用 S4_LLM_FILL_TIMEOUT_SEC（缺省沿用
   opencode_timeout_sec）。
2. 失败显式化：会话异常 / outputFile 不存在 → 直接 raise（错误信息保留原因），
   由上层记 fillError 标红目录项，不再回退任何脚本路径。
OpenCode 全部 mock，不依赖外部服务。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import technical_gap_ai_fill as ai_fill


class _FakeOpencodeClient:
    """记录构造参数与调用参数的 OpencodeClient 替身。"""

    instances: list["_FakeOpencodeClient"] = []
    error: Exception | None = None
    result: dict = {"outputFile": "unused"}

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls: list[dict] = []
        _FakeOpencodeClient.instances.append(self)

    def run_bid_tech_table_filler_with_trace(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if _FakeOpencodeClient.error is not None:
            raise _FakeOpencodeClient.error
        return dict(_FakeOpencodeClient.result)


class TableFillerLlmOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.manifest_path = self.base / "table_fill_input.json"
        self.manifest_path.write_text("{}", encoding="utf-8")
        _FakeOpencodeClient.instances = []
        _FakeOpencodeClient.error = None
        _FakeOpencodeClient.result = {"outputFile": "unused"}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *, timeout_sec=None) -> dict:
        with (
            patch.object(ai_fill.settings, "s4_llm_fill_timeout_sec", timeout_sec),
            patch.object(ai_fill, "OpencodeClient", _FakeOpencodeClient),
        ):
            return ai_fill.run_technical_table_filler_skill(self.manifest_path)

    def test_llm_prompt_and_no_early_tool_command(self) -> None:
        output = self.base / "filled.docx"
        output.write_bytes(b"docx")
        _FakeOpencodeClient.result = {"outputFile": str(output)}
        result = self._run(timeout_sec=3600.0)
        self.assertEqual(result["outputFile"], str(output))
        client = _FakeOpencodeClient.instances[0]
        # LLM 会话明显变长：独立超时生效
        self.assertEqual(client.kwargs.get("timeout_ms"), 3600000)
        call = client.calls[0]
        # 多轮读写不提前收口：等会话自然结束（对齐 factcurate 先例）
        self.assertEqual(call["early_tool_command"], "")
        prompt = call["prompt"]
        self.assertIn(f"s4fill-prepare {self.manifest_path}", prompt)
        self.assertIn(f"s4fill-apply {self.manifest_path}", prompt)

    def test_llm_timeout_defaults_to_opencode_timeout(self) -> None:
        output = self.base / "filled.docx"
        output.write_bytes(b"docx")
        _FakeOpencodeClient.result = {"outputFile": str(output)}
        self._run(timeout_sec=None)
        client = _FakeOpencodeClient.instances[0]
        self.assertEqual(
            client.kwargs.get("timeout_ms"),
            int(ai_fill.settings.opencode_timeout_sec * 1000),
        )

    def test_session_failure_raises_with_reason(self) -> None:
        _FakeOpencodeClient.error = RuntimeError("connection refused")
        # LLM 会话失败显式抛出（保留原因），由上层记 fillError，不再回退脚本
        with self.assertRaisesRegex(RuntimeError, "LLM 附表填写会话失败.*connection refused"):
            self._run()

    def test_missing_output_file_raises_with_reason(self) -> None:
        _FakeOpencodeClient.result = {"outputFile": str(self.base / "not_written.docx")}
        with self.assertRaisesRegex(RuntimeError, "未产出有效输出文件"):
            self._run()

    def test_empty_output_file_raises_with_reason(self) -> None:
        _FakeOpencodeClient.result = {"outputFile": ""}
        with self.assertRaisesRegex(RuntimeError, "未产出有效输出文件"):
            self._run()


if __name__ == "__main__":
    unittest.main()
