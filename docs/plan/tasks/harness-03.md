---
id: harness-03
scope: Harness / opencode 客户端
status: done
depends-on: [harness-06]
---

# harness-03：send_prompt 中途重试与断线恢复（短板 3）

> 已由 engine-04（波次 B2）接管，以 engine-* 为准；本文件保留现状证据。

## objective

生成中途（send_prompt 及轮询阶段）的可恢复错误支持重试/续跑，长任务（上限 1800s）不再一次抖动整轮作废。

## context

- `docs/anbc_doc/架构总览/05-Harness基建.md` §5 短板 3
- harness-06（重试建立在异步客户端之上）
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md`

## path

- harness-01/06 后的客户端会话与轮询模块
- 调用方错误处理：`bid_directory_flow`、`bid_generation_flow`、parsing 分片

## 现状（2026-08-12 复核证据）

- 重试只覆盖 `create_session`（opencode_client.py:64-114，`_SESSION_CREATE_RETRY_DELAYS_SEC` + 429/502/503/504 白名单）。
- `send_prompt`（:116-159）任何错误直接抛 RuntimeError；轮询阶段断线同理。
- `:30` 的 `OUTLINE_DECISION_SESSION_MAX_ATTEMPTS=3` 是另起会话级重试，不覆盖生成中断。

## 改造方案

1. 区分错误类型：网络抖动/5xx/429 → 带退避重试（复用现有白名单思路）；业务错误 → 直接失败。
2. 轮询断线：先尝试重连同一会话继续轮询（会话还在 opencode 侧跑着），重连失败再判失败。
3. send_prompt 重发要先确认幂等性：若 opencode 不支持同会话重复 message 去重，则策略是「重连轮询」而非「重发 prompt」，实施时以 opencode API 实际语义为准。
4. 重试次数/间隔做成配置项，代码默认值本地安全。

## verification

- 用故障注入 mock（中途断连、偶发 502）验证：可恢复错误重试成功、不可恢复错误显式失败且保留现场。
