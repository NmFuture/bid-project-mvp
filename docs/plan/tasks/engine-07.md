---
id: engine-07
scope: AgentEngine / CodexEngine
status: pending
depends-on: [engine-02]
---

# engine-07（波次 C1，新增）：CodexEngine 实现

## objective

实现 `CodexEngine`：`codex exec` 子进程 + JSON 事件流，借 Harbor 的 `BaseInstalledAgent` 模式（CLI_FLAGS / ENV_VARS 映射、ErrorPattern 错误归类），接入 `AgentEngine` 协议。

## context

- `docs/20260813-AgentEngine多内核引擎改造方案.md` §4.2、§6 波次 C1、§7「进程池上限与超时回收」
- prior art：`harbor-framework/harbor` 的 `BaseAgent` / `BaseInstalledAgent` / `AgentFactory` / `Codex.CLI_FLAGS`
- engine-02 产出（`on_tool_completed` 回调语义）

## path

- 新建 `code/sewpg-bid-backend/app/services/agent_engine/codex_engine.py`
- `factory.py`（注册 `codex`）
- `agent_engine/monitor.py`（如公共监管器已抽出则复用，否则本任务落地）

## 改造方案

1. `run_session` = 拼 `codex exec ... --json --resume <id>` → 子进程 → 流式读 stdout JSON 事件。
2. CLI_FLAGS / ENV_VARS 映射：reasoning_effort、模型、`--skip-git-repo-check` 等。
3. ErrorPattern：CLI 错误输出归类成统一异常（对齐 `errors.py`）。
4. 会话模型：一个 session ≈ 一个 exec 进程；`abort` = kill；`resume` = `--resume`。进程池上限 + 孤儿进程回收（与 engine-06 并发预算合并设计）。
5. 早期收割：事件流结构化，`ToolCompletedEvent` 由 bash 工具调用事件直接映射，复用 `on_tool_completed` 语义。
6. 「按请求切 provider」若不支持，降级为会话级固定 provider 并显式记录（方案 §3 注、§6 风险）。

## verification

- 单测覆盖事件映射、错误归类、abort/resume；mock 子进程事件流。
- 真实联通性验证留待 engine-09 PoC。
