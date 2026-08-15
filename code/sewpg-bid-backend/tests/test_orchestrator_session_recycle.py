from __future__ import annotations

import unittest
from unittest.mock import patch
from app.services.bid_parse_cancel import ParseCancelledError
from app.services.agent_engine.base import EngineRunResult
from app.services.agent_engine.opencode_engine import OpencodeEngine


class OrchestratorSessionRecycleTests(unittest.IsolatedAsyncioTestCase):

    """B3（engine-05）：编排层在会话终态（成功/失败/取消）调用 delete_session 回收。"""



    @staticmethod
    async def _passthrough_extractor(response: dict) -> dict:
        return {"echo": response}



    async def test_traced_session_recycles_on_success(self) -> None:
        client = OpencodeEngine()
        with (
            patch.object(client, "create_session", return_value="ses-trace-ok"),
            patch.object(client, "_send_prompt_with_session_polling", return_value={"parts": []}),
            patch.object(client, "delete_session") as delete,
        ):
            result = await client._orchestrator._run_traced_session(
                session_title="任务",
                prompt_text="prompt",
                extractor=self._passthrough_extractor,
            )

        self.assertIn("opencodeOutput", result)
        delete.assert_awaited_once_with("ses-trace-ok")



    async def test_traced_session_recycles_on_failure(self) -> None:
        client = OpencodeEngine()
        with (
            patch.object(client, "create_session", return_value="ses-trace-err"),
            patch.object(client, "_send_prompt_with_session_polling", side_effect=RuntimeError("轮询失败")),
            patch.object(client, "delete_session") as delete,
        ):
            with self.assertRaisesRegex(RuntimeError, "轮询失败"):
                await client._orchestrator._run_traced_session(
                    session_title="任务",
                    prompt_text="prompt",
                    extractor=self._passthrough_extractor,
                )

        delete.assert_awaited_once_with("ses-trace-err")



    async def test_traced_session_recycles_on_cancel(self) -> None:
        client = OpencodeEngine()
        with (
            patch.object(client, "create_session", return_value="ses-trace-cancel"),
            patch.object(client, "abort_session", return_value=True),
            patch.object(client, "delete_session") as delete,
        ):
            with self.assertRaises(ParseCancelledError):
                await client._orchestrator._run_traced_session(
                    session_title="任务",
                    prompt_text="prompt",
                    cancel_check=lambda: True,
                    extractor=self._passthrough_extractor,
                    abort_on_cancel=True,
                )

        delete.assert_awaited_once_with("ses-trace-cancel")



    async def test_recycle_failure_does_not_mask_business_result(self) -> None:
        client = OpencodeEngine()
        with (
            patch.object(client, "create_session", return_value="ses-recycle-err"),
            patch.object(client, "_send_prompt_with_session_polling", return_value={"parts": []}),
            patch.object(client, "delete_session", side_effect=RuntimeError("回收失败")),
        ):
            result = await client._orchestrator._run_traced_session(
                session_title="任务",
                prompt_text="prompt",
                extractor=self._passthrough_extractor,
            )

        self.assertIn("opencodeOutput", result)



    async def test_shard_session_recycles_on_success(self) -> None:
        client = OpencodeEngine()
        with (
            patch.object(client, "create_session", return_value="ses-shard"),
            patch.object(
                client,
                "run_session",
                return_value=EngineRunResult(
                    session_id="ses-shard",
                    reply_text="",
                    trace={"sessionId": "ses-shard", "status": "received"},
                ),
            ) as run_session,
            patch.object(client, "delete_session") as delete,
        ):
            result = await client._orchestrator.run_tender_parse_shard_with_trace("prompt")

        self.assertIn("opencodeOutput", result)
        run_session.assert_awaited_once()
        delete.assert_awaited_once_with("ses-shard")



    async def test_decision_session_recycles_every_attempt(self) -> None:
        client = OpencodeEngine()
        responses = [
            {"info": {"error": {"name": "StreamError", "data": {"message": "帧错乱"}}}},
            {},
        ]
        # 第 1 次调用是报错路径的落盘核查（未判完 → 触发重试），第 2 次是重试成功后的终态校验。
        decision_states = iter([{"complete": False}, {"complete": True}])

        async def fake_polling(*_args: object, **_kwargs: object) -> dict:
            return responses.pop(0)

        with (
            patch.object(client, "create_session", side_effect=["ses-try-1", "ses-try-2"]),
            patch.object(client, "_send_prompt_with_session_polling", side_effect=fake_polling),
            patch.object(client, "delete_session") as delete,
            patch("app.services.agent_engine.orchestrator.asyncio.sleep"),
        ):
            result = await client._orchestrator.run_outline_decision_session(
                "prompt",
                session_title="章节决策",
                completion_validator=lambda: next(decision_states),
            )

        self.assertEqual(result["sessionId"], "ses-try-2")
        self.assertEqual([call.args[0] for call in delete.await_args_list], ["ses-try-1", "ses-try-2"])



    async def test_outline_handoff_and_finalize_sessions_all_recycled(self) -> None:
        client = OpencodeEngine()
        handoff_states = iter([{"complete": False}, {"complete": True}])

        async def fake_polling(session_id: str, *_args: object, **kwargs: object) -> dict:
            validator = kwargs.get("assistant_stop_validator")
            if validator is not None:
                validated = validator()
                return {"_assistantStopValidation": validated}
            return {"parts": [{"type": "text", "text": '{"summary":"ok","nodes":[]}'}]}

        with (
            patch.object(
                client,
                "create_session",
                side_effect=["ses-handoff-1", "ses-handoff-2", "ses-final"],
            ),
            patch.object(client, "_send_prompt_with_session_polling", side_effect=fake_polling),
            patch.object(client, "delete_session") as delete,
        ):
            await client._orchestrator.generate_outline_with_trace(
                "prompt",
                handoff_prompt_factory=lambda index: f"接力 {index}",
                handoff_state_callback=lambda _index: next(handoff_states),
            )

        self.assertEqual(
            [call.args[0] for call in delete.await_args_list],
            ["ses-handoff-1", "ses-handoff-2", "ses-final"],
        )
