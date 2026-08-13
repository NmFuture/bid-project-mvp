"""AgentEngine 包：引擎协议、工厂与各内核引擎实现（改造方案 §2）。

A0（engine-01）立边界：`base.py` 协议与公共类型、`factory.py` 工厂、
`opencode_engine.py`（原 `app/services/opencode_client.py` 纯改名迁入）、
`json_utils.py` / `trace.py` / `errors.py`（§5 引擎无关公共能力下沉）。
A1（engine-02）：`base.py` 增加 ToolCompletedEvent/EarlyCompletionPlan，
`orchestrator.py` 承载业务编排层（run_bid_* / _extract_*_json / 任务注册表），
引擎轮询循环改为 on_tool_completed 回调，不再出现业务命令字符串。
B1（engine-03）：协议与引擎/编排全量 async（`httpx.AsyncClient` + asyncio task
轮询，每会话 daemon 线程消除）；同步调用方经既有桥接（`run_awaitable_sync` /
`parsing._run_coroutine_blocking`）进入。
C3（engine-09）：S1 分片链路经 `AgentEngineFactory` 接线（`AGENT_ENGINE` 可切换，
默认恒为 opencode）；`OpencodeEngine` 补齐协议形态（`create_session -> str`、
`run_session`、`list_messages`），plan→协议回调适配落
`base.tool_completed_callback_from_plan`；codex/pi 按真实 CLI（0.147.0/0.73.1）
校准命令拼法与事件键（PoC 记录见 docs/plan/reviews/engine-09-poc.md）。
"""
