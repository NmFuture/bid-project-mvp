---
id: engine-08
scope: AgentEngine / PiEngine
status: done
depends-on: [engine-02]
---

# engine-08（波次 C2，新增）：PiEngine 实现

## objective

实现 `PiEngine`：Pi 的 RPC 模式（JSON-over-stdio 常驻服务），接入 `AgentEngine` 协议；重试/监管/超时回收等周边能力复用/补齐。

## context

- `docs/20260813-AgentEngine多内核引擎改造方案.md` §4.3、§6 波次 C2
- engine-02 产出（`on_tool_completed` 回调语义）；engine-07 若先行，进程管理模式对齐

## path

- 新建 `code/sewpg-bid-backend/app/services/agent_engine/pi_engine.py`
- `factory.py`（注册 `pi`）
- `agent_engine/monitor.py`（复用公共监管器）

## 改造方案

1. 起 RPC 进程，按 JSON 命令驱动、事件流推送；会话模型：多会话 = 多进程。
2. `abort` = RPC 停止命令或杀进程；进程池上限 + 孤儿回收。
3. 周边补齐：heartbeat、idle 超时、进度增量复用 `SessionMonitor`；事件协议版本显式记录。

## verification

- 单测覆盖 RPC 收发、事件映射、abort；真实联通性验证留待 engine-09 PoC。
