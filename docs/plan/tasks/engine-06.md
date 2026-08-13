---
id: engine-06
scope: AgentEngine / 并发治理统一
status: pending
depends-on: []
---

# engine-06（波次 B4，对应 harness-02）：并发治理统一

## objective

消除三个互不知晓的信号量池造成的「实际并发=各池之和」；章节并行度配置化；代码默认值与 compose 默认值对齐。进程型引擎（Codex/Pi）的进程池上限与本任务的并发预算合并设计。

## context

- `docs/20260813-AgentEngine多内核引擎改造方案.md` §6 波次 B4、§7「进程池上限与超时回收」
- `docs/plan/tasks/harness-02.md`（现状证据与文件清单以其为准）
- 根 AGENTS.md 配置分层规则（5090 取值只写 `docker-compose.5090.yml`）

## path

- `code/sewpg-bid-backend/app/services/agent_engine/` 或原位置（`_OPENCODE_REQUEST_SLOTS`）
- `code/sewpg-bid-backend/app/services/parsing.py`（`_S1_SHARD_REQUEST_SLOTS`）
- `code/sewpg-bid-backend/app/services/outline_generation.py`（章节并行度）
- `code/sewpg-bid-backend/app/core/config.py`（`OPENCODE_MAX_CONCURRENCY`）
- `code/docker-compose.yml` / `code/docker-compose.5090.yml`

## 现状

- 三个信号量池互不知晓：客户端请求槽、S1 分片槽（默认 7）、章节课槽（6+1 硬编码）；`OPENCODE_MAX_CONCURRENCY` 默认 8 与 compose `:-1` 不对齐。

## 改造方案

1. 单一并发预算（配置化），各池改为从预算申请。
2. 章节并行度配置化，代码默认值本地安全。
3. 代码默认值与 compose 默认值对齐；5090 取值只落 `docker-compose.5090.yml`。

## verification

- 与 CI 对齐后端测试全绿；并发上限行为有单测（mock 验证不超预算）。
