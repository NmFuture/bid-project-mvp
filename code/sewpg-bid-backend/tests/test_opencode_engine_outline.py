from __future__ import annotations

import asyncio
import json
import threading
from unittest.mock import MagicMock, patch
from app.services.agent_engine import orchestrator
from app.services.agent_engine.opencode_engine import (
    OUTLINE_DECISION_SESSION_MAX_ATTEMPTS,
    OpencodeEngine,
)

from opencode_engine_helpers import (
    OpencodeEngineTestBase,
)


class OpencodeEngineTests(OpencodeEngineTestBase):

    async def test_generate_outline_with_trace_defaults_to_no_early_tool_completion(self) -> None:
        client = OpencodeEngine()

        with (
            patch.object(client, "create_session", return_value="ses-outline"),
            patch.object(
                client,
                "_send_prompt_with_session_polling",
                return_value={
                    "parts": [
                        {
                            "type": "text",
                            "text": (
                                '{"schema_version":"bid-toc-json-v1",'
                                '"summary":{"total_items":0},"items":[]}'
                            ),
                        }
                    ]
                },
            ) as send_prompt,
            patch.object(client, "_build_output_trace", return_value={"status": "received"}),
        ):
            result = await client.generate_outline_with_trace("prompt")

        send_prompt.assert_called_once()
        self.assertIsNone(send_prompt.call_args.kwargs.get("early_completion"))
        self.assertEqual(result["schema_version"], "bid-toc-json-v1")



    async def test_run_outline_decision_session_uses_persisted_chapter_completion(self) -> None:
        client = OpencodeEngine()
        validator = MagicMock(return_value={"complete": True, "decidedCount": 18})
        with (
            patch.object(client, "create_session", return_value="ses-chapter-1"),
            patch.object(
                client,
                "_send_prompt_with_session_polling",
                return_value={"parts": [{"type": "text", "text": "done"}]},
            ) as send_prompt,
            patch.object(
                client,
                "_build_output_trace",
                return_value={"status": "received", "sessionId": "ses-chapter-1"},
            ),
        ):
            result = await client.run_outline_decision_session(
                "chapter prompt",
                session_title="S2 目录决策·第一章",
                completion_validator=validator,
            )

        self.assertEqual(result["sessionId"], "ses-chapter-1")
        self.assertTrue(result["state"]["complete"])
        self.assertIsNone(send_prompt.call_args.kwargs.get("early_completion"))
        self.assertTrue(callable(send_prompt.call_args.kwargs["assistant_stop_validator"]))



    async def test_run_outline_decision_session_retries_transient_session_error(self) -> None:
        """瞬时流错误重试一次即可续跑：decision-next 会把中断的批次原样带回，不会重复提交。"""
        client = OpencodeEngine()
        # 第一次会话报错（上游 SSE 帧错乱），第二次正常收尾
        responses = [
            {"info": {"error": {"name": "AI_JSONParseError", "message": "JSON parsing failed"}}},
            {"parts": [{"type": "text", "text": "done"}]},
        ]
        validator = MagicMock(side_effect=[
            {"complete": False, "decidedCount": 7},   # 报错后查落盘状态：确实没判完
            {"complete": True, "decidedCount": 18},   # 重试后判完
        ])
        with (
            patch.object(
                client,
                "create_session",
                side_effect=["ses-try-1", "ses-try-2"],
            ) as create_session,
            patch.object(
                client,
                "_send_prompt_with_session_polling",
                side_effect=responses,
            ) as send_prompt,
            patch.object(
                client,
                "_build_output_trace",
                return_value={"status": "received", "sessionId": "ses-try-2"},
            ),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep", return_value=None),
        ):
            result = await client.run_outline_decision_session(
                "chapter prompt",
                session_title="S2 目录决策·第一章",
                completion_validator=validator,
            )

        self.assertEqual(create_session.call_count, 2, "重试必须开新会话，不能复用报错的会话")
        self.assertEqual(send_prompt.call_count, 2)
        self.assertEqual(result["sessionId"], "ses-try-2")
        self.assertTrue(result["state"]["complete"])



    async def test_run_outline_decision_session_keeps_result_when_error_arrives_after_completion(self) -> None:
        """决策以落盘状态为准：错误发生在结果写盘之后时，不该丢掉已经判完的整章。"""
        client = OpencodeEngine()
        validator = MagicMock(return_value={"complete": True, "decidedCount": 18})
        with (
            patch.object(client, "create_session", return_value="ses-late-error") as create_session,
            patch.object(
                client,
                "_send_prompt_with_session_polling",
                return_value={"info": {"error": {"name": "AI_JSONParseError", "message": "boom"}}},
            ),
            patch.object(
                client,
                "_build_output_trace",
                return_value={"status": "received", "sessionId": "ses-late-error"},
            ),
        ):
            result = await client.run_outline_decision_session(
                "chapter prompt",
                session_title="S2 目录决策·第一章",
                completion_validator=validator,
            )

        self.assertEqual(create_session.call_count, 1, "已经判完就不该再开一次会话")
        self.assertTrue(result["state"]["complete"])



    async def test_run_outline_decision_session_gives_up_after_max_attempts(self) -> None:
        """一直失败要如实抛出，不能无限重试拖死整轮目录生成。"""
        client = OpencodeEngine()
        validator = MagicMock(return_value={"complete": False, "decidedCount": 0})
        with (
            patch.object(client, "create_session", return_value="ses-dead") as create_session,
            patch.object(
                client,
                "_send_prompt_with_session_polling",
                return_value={"info": {"error": {"name": "AI_APICallError", "message": "boom"}}},
            ),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep", return_value=None),
        ):
            with self.assertRaises(RuntimeError):
                await client.run_outline_decision_session(
                    "chapter prompt",
                    session_title="S2 目录决策·第一章",
                    completion_validator=validator,
                )

        self.assertEqual(create_session.call_count, OUTLINE_DECISION_SESSION_MAX_ATTEMPTS)



    async def test_generate_outline_with_trace_uses_fresh_sessions_for_bounded_handoffs(self) -> None:
        client = OpencodeEngine()
        final_response = {
            "parts": [
                {
                    "type": "text",
                    "text": (
                        '{"schema_version":"bid-toc-json-v1",'
                        '"summary":{"total_items":1},'
                        '"items":[{"title":"技术方案"}]}'
                    ),
                }
            ]
        }

        with (
            patch.object(
                client,
                "create_session",
                side_effect=[
                    "ses-checkpoint-1",
                    "ses-checkpoint-2",
                    "ses-final",
                ],
            ) as create_session,
            patch.object(
                client,
                "_send_prompt_with_session_polling",
                side_effect=[
                    {"parts": [{"type": "text", "text": '{"checkpoint":1}'}]},
                    {"parts": [{"type": "text", "text": '{"checkpoint":2}'}]},
                    final_response,
                ],
            ) as send_prompt,
            patch.object(
                client,
                "_build_output_trace",
                return_value={"status": "received", "sessionId": "ses-final"},
            ),
        ):
            result = await client.generate_outline_with_trace(
                "final prompt",
                early_tool_command="s2outline-finalize",
                handoff_prompt_factory=lambda index: f"checkpoint prompt {index}",
                handoff_state_callback=MagicMock(
                    side_effect=[
                        {"complete": False, "decidedCount": 6},
                        {"complete": True, "decidedCount": 10},
                    ]
                ),
            )

        self.assertEqual(create_session.call_count, 3)
        self.assertEqual(
            [call.args[1] for call in send_prompt.call_args_list],
            ["checkpoint prompt 1", "checkpoint prompt 2", "final prompt"],
        )
        self.assertEqual(
            [call.kwargs["early_completion"].display_label for call in send_prompt.call_args_list],
            ["s2outline-decision-batch", "s2outline-decision-batch", "s2outline-finalize"],
        )
        self.assertEqual(
            result["opencodeOutput"]["sessionIds"],
            ["ses-checkpoint-1", "ses-checkpoint-2", "ses-final"],
        )
        self.assertEqual(result["opencodeOutput"]["handoffSessionCount"], 2)



    async def test_s2_outline_finalize_tool_output_is_terminal(self) -> None:
        final_output = (
            '{"schema_version":"technical-outline.v1",'
            '"outputFile":"/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/toc.json",'
            '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
        )
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "s2outline finalize /data/documents/PRJ/technical-workspace/s2_toc_workdir.new/s2_input.json"},
                            "exit": 0,
                            "output": final_output,
                        },
                    }
                ]
            }
        ]

        output = orchestrator.find_completed_bash_tool_output(messages, "s2outline-finalize")

        self.assertIn('"total_nodes":64', output)



    async def test_s2_outline_terminal_output_rejects_noncanonical_agent_commands(self) -> None:
        final_output = (
            '{"schema_version":"technical-outline.v1",'
            '"outputFile":"/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/toc.json",'
            '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
        )
        commands = [
            (
                "cd /workspace/.opencode/skills/bid-tech-outline-generator && "
                "python3 -m scripts.run_from_manifest finalize "
                "/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/s2_input.json 2>&1"
            ),
            (
                "python3 /workspace/.opencode/skills/bid-tech-outline-generator/"
                "scripts/run_from_manifest.py finalize "
                "/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/s2_input.json"
            ),
            "python3 /opt/agent-tools/custom_outline_writer.py --project PRJ",
        ]

        for command in commands:
            with self.subTest(command=command):
                messages = [
                    {
                        "parts": [
                            {
                                "type": "tool",
                                "tool": "bash",
                                "state": {
                                    "status": "completed",
                                    "input": {"command": command},
                                    "exit": 0,
                                    "output": final_output,
                                },
                            }
                        ]
                    }
                ]

                output = orchestrator.find_completed_bash_tool_output(messages, "s2outline-finalize")

                self.assertEqual(output, "")



    async def test_s2_outline_terminal_output_rejects_finalize_command_suffixes(self) -> None:
        final_output = (
            '{"schema_version":"technical-outline.v1",'
            '"outputFile":"/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/toc.json",'
            '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
        )
        manifest = "/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/s2_input.json"
        commands = [
            f"s2outline finalize {manifest} && python3 /tmp/fake.py",
            f"s2outline finalize {manifest} || python3 /tmp/fake.py",
            f"s2outline finalize {manifest} ; python3 /tmp/fake.py",
            f"s2outline finalize {manifest};true",
            f"s2outline finalize {manifest}>/tmp/final.json",
            f"/tmp/s2outline finalize {manifest}",
            f"s2outline finalize {manifest} --force",
            f"s2outline finalize {manifest} 2>&1",
        ]

        for command in commands:
            with self.subTest(command=command):
                messages = [
                    {
                        "parts": [
                            {
                                "type": "tool",
                                "tool": "bash",
                                "state": {
                                    "status": "completed",
                                    "input": {"command": command},
                                    "exit": 0,
                                    "output": final_output,
                                },
                            }
                        ]
                    }
                ]

                output = orchestrator.find_completed_bash_tool_output(messages, "s2outline-finalize")

                self.assertEqual(output, "")



    async def test_s2_outline_terminal_output_accepts_tool_metadata_stdout(self) -> None:
        final_output = (
            '{"schema_version":"technical-outline.v1",'
            '"outputFile":"/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/toc.json",'
            '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
        )
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {
                                "command": "s2outline finalize /data/documents/PRJ/technical-workspace/s2_toc_workdir.new/s2_input.json"
                            },
                            "metadata": {"exit": 0, "output": final_output},
                        },
                    }
                ]
            }
        ]

        output = orchestrator.find_completed_bash_tool_output(messages, "s2outline-finalize")

        self.assertIn('"workflowStage":"finalized"', output)



    async def test_s2_outline_terminal_output_requires_bash_tool_name(self) -> None:
        final_output = (
            '{"schema_version":"technical-outline.v1",'
            '"outputFile":"/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/toc.json",'
            '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
        )
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "agent-outline-writer",
                        "state": {
                            "status": "completed",
                            "input": {
                                "command": "s2outline finalize /data/documents/PRJ/technical-workspace/s2_toc_workdir.new/s2_input.json"
                            },
                            "metadata": {"exit": 0, "output": final_output},
                        },
                    }
                ]
            }
        ]

        output = orchestrator.find_completed_bash_tool_output(messages, "s2outline-finalize")

        self.assertEqual(output, "")



    async def test_s2_outline_terminal_output_rejects_failed_tool_metadata_exit(self) -> None:
        final_output = (
            '{"schema_version":"technical-outline.v1",'
            '"outputFile":"/data/documents/PRJ/technical-workspace/s2_toc_workdir.new/toc.json",'
            '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
        )
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {
                                "command": "s2outline finalize /data/documents/PRJ/technical-workspace/s2_toc_workdir.new/s2_input.json"
                            },
                            "metadata": {"exit": 1, "output": final_output},
                        },
                    }
                ]
            }
        ]

        output = orchestrator.find_completed_bash_tool_output(messages, "s2outline-finalize")

        self.assertEqual(output, "")



    async def test_s2_outline_non_terminal_outputs_do_not_trigger_early_completion(self) -> None:
        non_terminal_output = '{"status":"passed","summary":{"workflowStage":"validated"}}'
        for command in [
            "s2outline prepare /data/documents/PRJ/s2_input.json",
            "s2outline status /data/documents/PRJ/s2_input.json",
            "s2outline validate /data/documents/PRJ/s2_input.json",
            "s2toc /data/documents/PRJ/s2_input.json",
        ]:
            with self.subTest(command=command):
                messages = [
                    {
                        "parts": [
                            {
                                "type": "tool",
                                "tool": "bash",
                                "state": {
                                    "status": "completed",
                                    "input": {"command": command},
                                    "exit": 0,
                                    "output": non_terminal_output,
                                },
                            }
                        ]
                    }
                ]

                output = orchestrator.find_completed_bash_tool_output(messages, "s2outline-finalize")

                self.assertEqual(output, "")



    async def test_s2_outline_finalize_requires_terminal_json_output(self) -> None:
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "s2outline finalize /data/documents/PRJ/s2_input.json"},
                            "exit": 0,
                            "output": '{"status":"waiting","summary":{"total_items":0}}',
                        },
                    },
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "s2outline finalize /data/documents/PRJ/s2_input.json"},
                            "exit": 0,
                            "output": (
                                '{"schema_version":"technical-outline.v1",'
                                '"outputFile":"/data/documents/PRJ/toc.json",'
                                '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
                            ),
                        },
                    },
                ]
            }
        ]

        output = orchestrator.find_completed_bash_tool_output(messages, "s2outline-finalize")

        self.assertIn('"outputFile"', output)
        self.assertIn('"total_nodes":64', output)



    async def test_s2_outline_waits_for_finalize_after_prompt_timeout(self) -> None:
        client = OpencodeEngine()
        finalize_output = (
            '{"schema_version":"technical-outline.v1",'
            '"outputFile":"/data/documents/PRJ/toc.json",'
            '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
        )
        validation_messages = [
            {
                "info": {"role": "assistant", "id": "msg-validate"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "s2outline validate /data/documents/PRJ/s2_input.json"},
                            "exit": 0,
                            "output": '{"status":"passed"}',
                        },
                    }
                ],
            }
        ]
        finalized_messages = [
            *validation_messages,
            {
                "info": {"role": "assistant", "id": "msg-finalize"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "s2outline finalize /data/documents/PRJ/s2_input.json"},
                            "exit": 0,
                            "output": finalize_output,
                        },
                    }
                ],
            },
        ]
        snapshots = iter([validation_messages, finalized_messages])

        def list_messages(session_id: str) -> list[dict]:
            try:
                return next(snapshots)
            except StopIteration:
                return finalized_messages

        with (
            patch.object(client, "send_prompt", side_effect=RuntimeError("futurecode generate timeout")),
            patch.object(client, "list_session_messages", side_effect=list_messages) as list_session_messages,
            patch.object(client, "abort_session", return_value=True) as abort_session,
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep", return_value=None),
        ):
            response = await client._send_prompt_with_session_polling(
                "ses-s2-outline",
                "prompt",
                early_completion=self._plan(client, "s2outline-finalize"),
            )

        self.assertTrue(response["_earlyCompletion"])
        self.assertEqual(response["_completionSource"], "s2outline-finalize")
        self.assertIn('"total_nodes":64', response["parts"][0]["text"])
        self.assertGreaterEqual(list_session_messages.call_count, 2)
        abort_session.assert_called_once_with("ses-s2-outline")



    async def test_s2_outline_early_completion_aborts_and_waits_for_active_prompt_worker(self) -> None:
        client = OpencodeEngine()
        release_worker = threading.Event()
        worker_finished = threading.Event()
        finalize_output = (
            '{"schema_version":"technical-outline.v1",'
            '"outputFile":"/data/documents/PRJ/toc.json",'
            '"summary":{"total_nodes":64,"workflowStage":"finalized"}}'
        )
        finalized_messages = [
            {
                "info": {"role": "assistant", "id": "msg-finalize"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "s2outline finalize /data/documents/PRJ/s2_input.json"},
                            "exit": 0,
                            "output": finalize_output,
                        },
                    }
                ],
            }
        ]

        async def blocked_send_prompt(_session_id: str, _prompt: str, **_kwargs) -> dict:
            await asyncio.to_thread(release_worker.wait, 5)
            worker_finished.set()
            return {"parts": [{"type": "text", "text": finalize_output}]}

        def abort_session(_session_id: str) -> bool:
            release_worker.set()
            return True

        try:
            with (
                patch.object(client, "send_prompt", side_effect=blocked_send_prompt),
                patch.object(client, "list_session_messages", return_value=finalized_messages),
                patch.object(
                    client,
                    "_get_session_output_snapshot",
                    return_value={"signature": ("finalized", ())},
                ),
                patch.object(client, "abort_session", side_effect=abort_session) as abort_session_mock,
            ):
                response = await client._send_prompt_with_session_polling(
                    "ses-s2-active",
                    "prompt",
                    early_completion=self._plan(client, "s2outline-finalize"),
                )
        finally:
            release_worker.set()

        self.assertTrue(response["_earlyCompletion"])
        abort_session_mock.assert_called_once_with("ses-s2-active")
        self.assertTrue(worker_finished.is_set())



    async def test_s2_outline_stopped_session_uses_terminal_validator_for_noncanonical_command(self) -> None:
        client = OpencodeEngine()
        finalized_payload = {
            "schema_version": "technical-outline.v1",
            "outputFile": "/data/documents/PRJ/toc.json",
            "summary": {"total_nodes": 64, "workflowStage": "finalized"},
        }
        commands = [
            "s2outline finalize /data/documents/PRJ/s2_input.json",
            "s2outline finalize /data/documents/PRJ/s2_input.json 333>&1",
        ]

        for command in commands:
            with self.subTest(command=command):
                release_worker = threading.Event()
                stopped_messages = [
                    {
                        "info": {"role": "assistant", "id": "msg-final", "finish": "stop"},
                        "parts": [
                            {
                                "type": "tool",
                                "tool": "bash",
                                "state": {
                                    "status": "completed",
                                    "input": {"command": command},
                                    "exit": 0,
                                    "output": json.dumps(finalized_payload),
                                },
                            }
                        ],
                    }
                ]

                async def blocked_send_prompt(_session_id: str, _prompt: str, **_kwargs) -> dict:
                    await asyncio.to_thread(release_worker.wait, 5)
                    return {"parts": []}

                def abort_session(_session_id: str) -> bool:
                    release_worker.set()
                    return True

                with (
                    patch.object(client, "send_prompt", side_effect=blocked_send_prompt),
                    patch.object(client, "list_session_messages", return_value=stopped_messages),
                    patch.object(
                        client,
                        "_get_session_output_snapshot",
                        return_value={"signature": ("stopped", ())},
                    ),
                    patch.object(client, "abort_session", side_effect=abort_session) as abort_session_mock,
                    patch("app.services.agent_engine.opencode_engine.asyncio.sleep", return_value=None),
                ):
                    response = await client._send_prompt_with_session_polling(
                        "ses-s2-stopped",
                        "prompt",
                        early_completion=self._plan(
                            client,
                            "s2outline-finalize",
                            terminal_validator=lambda: finalized_payload,
                        ),
                    )

                self.assertTrue(response["_earlyCompletion"])
                self.assertEqual(response["_completionSource"], "s2outline-terminal-validator")
                self.assertIn('"workflowStage": "finalized"', response["parts"][0]["text"])
                abort_session_mock.assert_called_once_with("ses-s2-stopped")



    async def test_s2_outline_finalize_tool_stops_before_assistant_finishes(self) -> None:
        client = OpencodeEngine()
        finalized_payload = {
            "schema_version": "technical-outline.v1",
            "outputFile": "/data/documents/PRJ/toc.json",
            "summary": {"total_nodes": 64, "workflowStage": "finalized"},
        }
        finalized_messages = [
            {
                "info": {"role": "assistant", "id": "msg-finalize", "finish": "tool-calls"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {
                                "command": "s2outline finalize /data/documents/PRJ/s2_input.json"
                            },
                            "exit": 0,
                            "output": json.dumps(finalized_payload),
                        },
                    }
                ],
            }
        ]

        with (
            patch.object(client, "list_session_messages", return_value=finalized_messages),
            patch.object(client, "_stop_session_after_early_completion") as stop_session,
        ):
            response = await client._wait_for_early_completion_after_prompt_return(
                session_id="ses-s2-finalized",
                idle_timeout=0.01,
                stream_callback=None,
                plan=self._plan(client, "s2outline-finalize", terminal_validator=lambda: finalized_payload),
            )

        self.assertTrue(response["_earlyCompletion"])
        self.assertEqual(response["_completionSource"], "s2outline-terminal-validator")
        stop_session.assert_called_once_with("ses-s2-finalized", command_label="s2outline finalize")



    async def test_s2_outline_combined_finalize_tool_stops_before_assistant_finishes(self) -> None:
        client = OpencodeEngine()
        finalized_payload = {
            "schema_version": "technical-outline.v1",
            "outputFile": "/data/documents/PRJ/toc.json",
            "summary": {"total_nodes": 270, "workflowStage": "finalized"},
        }
        finalized_messages = [
            {
                "info": {"role": "assistant", "id": "msg-finalize", "finish": "tool-calls"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {
                                "command": (
                                    "s2outline section /data/documents/PRJ/s2_input.json TEN-2:S0279 "
                                    "--max-chars 30000 && "
                                    "s2outline finalize /data/documents/PRJ/s2_input.json"
                                )
                            },
                            "exit": 0,
                            "output": "...output truncated...",
                        },
                    }
                ],
            }
        ]

        with (
            patch.object(client, "list_session_messages", return_value=finalized_messages),
            patch.object(client, "_stop_session_after_early_completion") as stop_session,
        ):
            response = await client._wait_for_early_completion_after_prompt_return(
                session_id="ses-s2-combined-finalize",
                idle_timeout=0.01,
                stream_callback=None,
                plan=self._plan(client, "s2outline-finalize", terminal_validator=lambda: finalized_payload),
            )

        self.assertTrue(response["_earlyCompletion"])
        self.assertEqual(response["_completionSource"], "s2outline-terminal-validator")
        stop_session.assert_called_once_with("ses-s2-combined-finalize", command_label="s2outline finalize")



    async def test_s2_outline_terminal_validator_runs_once_per_finalize_tool_call(self) -> None:
        client = OpencodeEngine()
        failed_finalize_messages = [
            {
                "info": {"role": "assistant", "id": "msg-failed-finalize", "finish": "tool-calls"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {
                                "command": "s2outline finalize /data/documents/PRJ/s2_input.json"
                            },
                            "exit": 0,
                            "output": "evidenceId not authorized",
                        },
                    }
                ],
            }
        ]
        validator_calls = 0

        def invalid_terminal_output() -> dict:
            nonlocal validator_calls
            validator_calls += 1
            raise RuntimeError("not finalized")

        with (
            patch.object(client, "list_session_messages", return_value=failed_finalize_messages),
            patch("app.services.agent_engine.orchestrator._raise_command_stalled", return_value=None),
            patch("app.services.agent_engine.opencode_engine.asyncio.sleep", return_value=None),
        ):
            response = await client._wait_for_early_completion_after_prompt_return(
                session_id="ses-s2-failed-finalize",
                idle_timeout=0.01,
                stream_callback=None,
                plan=self._plan(client, "s2outline-finalize", terminal_validator=invalid_terminal_output),
            )

        self.assertIsNone(response)
        self.assertEqual(validator_calls, 1)



    async def test_s2_outline_stopped_session_releases_prompt_when_terminal_validation_fails(self) -> None:
        client = OpencodeEngine()
        release_worker = threading.Event()
        stopped_messages = [
            {
                "info": {"role": "assistant", "id": "msg-final", "finish": "stop"},
                "parts": [{"type": "text", "text": "done"}],
            }
        ]

        async def blocked_send_prompt(_session_id: str, _prompt: str, **_kwargs) -> dict:
            await asyncio.to_thread(release_worker.wait, 5)
            return {"parts": []}

        def abort_session(_session_id: str) -> bool:
            release_worker.set()
            return True

        with (
            patch.object(client, "send_prompt", side_effect=blocked_send_prompt),
            patch.object(client, "list_session_messages", return_value=stopped_messages),
            patch.object(
                client,
                "_get_session_output_snapshot",
                return_value={"signature": ("stopped", ())},
            ),
            patch.object(client, "abort_session", side_effect=abort_session) as abort_session_mock,
        ):
            with self.assertRaisesRegex(RuntimeError, "未通过 finalize 校验"):
                await client._send_prompt_with_session_polling(
                    "ses-s2-invalid",
                    "prompt",
                    early_completion=self._plan(
                        client,
                        "s2outline-finalize",
                        terminal_validator=lambda: (_ for _ in ()).throw(RuntimeError("invalid output")),
                    ),
                )

        abort_session_mock.assert_called_once_with("ses-s2-invalid")
