"""AgentEngine 包：引擎协议、工厂与各内核引擎实现（改造方案 §2）。

A0（engine-01）立边界：`base.py` 协议与公共类型、`factory.py` 工厂、
`opencode_engine.py`（原 `app/services/opencode_client.py` 纯改名迁入）、
`json_utils.py` / `trace.py` / `errors.py`（§5 引擎无关公共能力下沉）。
A1（engine-02）：`base.py` 增加 ToolCompletedEvent/EarlyCompletionPlan，
`orchestrator.py` 承载业务编排层（run_bid_* / _extract_*_json / 任务注册表），
引擎轮询循环改为 on_tool_completed 回调，不再出现业务命令字符串。
"""
