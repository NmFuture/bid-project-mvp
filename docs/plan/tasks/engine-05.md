---
id: engine-05
scope: AgentEngine / 会话生命周期回收
status: pending
depends-on: [engine-01]
---

# engine-05（波次 B3，对应 harness-04）：会话生命周期回收

## objective

会话用完即删（`delete_session`），并给 `opencode_data` 卷建立清理策略，消除无限增长。

## context

- `docs/20260813-AgentEngine多内核引擎改造方案.md` §3（协议含 `delete_session`）、§6 波次 B3
- `docs/plan/tasks/harness-04.md`（现状证据以其为准）

## path

- `code/sewpg-bid-backend/app/services/agent_engine/opencode_engine.py`（DELETE session 调用）
- 编排层/调用方：会话结束路径补 delete
- `code/scripts/`（卷清理脚本）、`code/docker-compose.yml`（:341、:442 `opencode_data` 卷）

## 现状

- 客户端只有 `abort_session`（POST `/session/{id}/abort`），无 DELETE session 调用；`opencode_data` 卷在 scripts/ 与 entrypoint 中均无清理逻辑，无限增长。

## 改造方案

1. 实现 `delete_session`（DELETE `/session/{id}`），失败显式记录不吞异常。
2. 编排层在会话终态（成功/失败/取消）调用回收；评估 try/finally 保证。
3. 卷清理脚本 + 文档说明清理策略（保留窗口、手动/定时触发）。

## verification

- 与 CI 对齐后端测试全绿；delete 路径有单测覆盖（含失败分支）。
