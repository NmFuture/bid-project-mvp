"""技术标附表 AI 填写 LLM 模式（S4_TABLE_FILL_MODE=llm）后端接线单测。

覆盖：
1. 默认 script 模式行为完全不变：prompt 仍是单次 s4fill，early_tool_command="s4fill"，
   回退不标注 fallbackReason。
2. llm 模式：prompt 走 prepare→plan→apply 流程，不传 early_tool_command（等会话自然
   结束），OpencodeClient 用 S4_LLM_FILL_TIMEOUT_SEC（缺省沿用 opencode_timeout_sec）。
3. llm 模式回退显式化：会话异常 / outputFile 不存在 → 落回本地脚本路径并在
   opencodeOutput 标注 fallbackReason。
OpenCode 与本地脚本执行全部 mock，不依赖外部服务。
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


class TableFillerLlmModeTests(unittest.TestCase):
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

    def _run(self, *, mode: str, timeout_sec=None, local_result=None) -> dict:
        local_result = local_result or {"outputFile": "local.docx", "opencodeOutput": {"status": "received"}}
        with (
            patch.object(ai_fill.settings, "s4_table_fill_mode", mode),
            patch.object(ai_fill.settings, "s4_llm_fill_timeout_sec", timeout_sec),
            patch.object(ai_fill, "OpencodeClient", _FakeOpencodeClient),
            patch.object(ai_fill, "_run_local_skill_runner", return_value=local_result) as local_runner,
        ):
            result = ai_fill.run_technical_table_filler_skill(self.manifest_path)
        self.local_runner = local_runner
        return result

    def test_script_mode_is_default_and_unchanged(self) -> None:
        # settings 缺省值必须是 script（本地安全默认）
        self.assertEqual(ai_fill.settings.s4_table_fill_mode, "script")
        result = self._run(mode="script")
        self.assertEqual(result["outputFile"], "unused")
        client = _FakeOpencodeClient.instances[0]
        # script 模式不覆盖超时（timeout_ms 由 client 默认逻辑取）
        self.assertNotIn("timeout_ms", client.kwargs)
        call = client.calls[0]
        self.assertEqual(call["early_tool_command"], "s4fill")
        self.assertIn(f"s4fill {self.manifest_path}", call["prompt"])
        self.assertNotIn("s4fill-prepare", call["prompt"])
        self.local_runner.assert_not_called()

    def test_llm_mode_prompt_and_no_early_tool_command(self) -> None:
        output = self.base / "filled.docx"
        output.write_bytes(b"docx")
        _FakeOpencodeClient.result = {"outputFile": str(output)}
        result = self._run(mode="llm", timeout_sec=3600.0)
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
        self.local_runner.assert_not_called()

    def test_llm_mode_timeout_defaults_to_opencode_timeout(self) -> None:
        output = self.base / "filled.docx"
        output.write_bytes(b"docx")
        _FakeOpencodeClient.result = {"outputFile": str(output)}
        self._run(mode="llm", timeout_sec=None)
        client = _FakeOpencodeClient.instances[0]
        self.assertEqual(
            client.kwargs.get("timeout_ms"),
            int(ai_fill.settings.opencode_timeout_sec * 1000),
        )

    def test_llm_mode_session_failure_falls_back_with_reason(self) -> None:
        _FakeOpencodeClient.error = RuntimeError("connection refused")
        result = self._run(mode="llm")
        # 落回本地脚本路径，opencodeOutput 显式标注回退原因，不再静默
        self.assertEqual(result["outputFile"], "local.docx")
        self.assertIn("connection refused", result["opencodeOutput"]["fallbackReason"])
        self.local_runner.assert_called_once()

    def test_llm_mode_missing_output_file_falls_back_with_reason(self) -> None:
        _FakeOpencodeClient.result = {"outputFile": str(self.base / "not_written.docx")}
        result = self._run(mode="llm")
        self.assertEqual(result["outputFile"], "local.docx")
        self.assertIn("未产出有效输出文件", result["opencodeOutput"]["fallbackReason"])

    def test_script_mode_fallback_has_no_fallback_reason(self) -> None:
        _FakeOpencodeClient.error = RuntimeError("connection refused")
        result = self._run(mode="script")
        self.assertEqual(result["outputFile"], "local.docx")
        self.assertNotIn("fallbackReason", result["opencodeOutput"])


if __name__ == "__main__":
    unittest.main()
