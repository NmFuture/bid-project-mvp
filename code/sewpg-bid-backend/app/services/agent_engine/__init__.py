"""AgentEngine 包：引擎协议、工厂与各内核引擎实现（改造方案 §2）。

A0（engine-01）只立边界：`base.py` 协议与公共类型、`factory.py` 工厂、
`opencode_engine.py`（原 `app/services/opencode_client.py` 纯改名迁入）、
`json_utils.py` / `trace.py` / `errors.py`（§5 引擎无关公共能力下沉）。
"""
