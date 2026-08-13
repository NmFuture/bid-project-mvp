---
id: engine-04
scope: AgentEngine / 重试与断线恢复
status: pending
depends-on: [engine-03]
---

# engine-04（波次 B2，对应 harness-03）：send_prompt 中途重试与断线恢复

## objective

生成中途（send_prompt 及轮询阶段）的可恢复错误支持重试/续跑，长任务（上限 1800s）不再一次抖动整轮作废。

## context

- `docs/20260813-AgentEngine多内核引擎改造方案.md` §6 波次 B2
- `docs/plan/tasks/harness-03.md`（现状证据以其为准）
- engine-03（重试建立在异步客户端之上）

## path

- `code/sewpg-bid-backend/app/services/agent_engine/`（会话与轮询模块）
- 调用方错误处理：`bid_directory_flow`、`bid_generation_flow`、parsing 分片

## 现状

- 重试只覆盖 `create_session`（原 opencode_client.py:64-114，`_SESSION_CREATE_RETRY_DELAYS_SEC` + 429/502/503/504 白名单）。
- `send_prompt` 任何错误直接抛 RuntimeError；轮询阶段断线同理。

## 改造方案

1. 定义可恢复错误分类（对齐 `errors.py` 的错误归一化），轮询断线自动重连续轮询。
2. send_prompt 幂等性评估：可安全重试的场景加重试（带退避），不可重试的显式报错。
3. 重试次数/退避做成配置项，代码默认值本地安全。

## verification

- 与 CI 对齐后端测试全绿；新增重试/断线恢复的单元测试（模拟 502/断连）。
