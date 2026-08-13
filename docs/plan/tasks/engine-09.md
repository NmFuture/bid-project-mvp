---
id: engine-09
scope: AgentEngine / 换内核 PoC
status: done
depends-on: [engine-07, engine-08]
---

# engine-09（波次 C3，新增）：Codex/Pi 换内核 PoC（S1 分片链路）

## objective

选 S1 分片会话 `run_tender_parse_shard_with_trace`（依赖最少链路）跑通 Codex/Pi，验证 `AGENT_ENGINE` 切换的语义等价性，产出是否进入生产的结论。

## context

- `docs/20260813-AgentEngine多内核引擎改造方案.md` §6 波次 C3、§8 PoC 判据
- `docs/anbc_doc/架构总览/opencode-链路与替换可行性示意.html`（替换可行性第 1 步）

## path

- `code/sewpg-bid-backend/app/services/parsing.py`（S1 分片链路，经编排层走工厂）
- `code/sewpg-bid-backend/app/services/agent_engine/`（factory 接线）
- PoC 记录：结果写入本任务文件或 `docs/plan/reviews/engine-09-01.md`

## 改造方案

1. S1 分片链路经 `AgentEngineFactory` 取引擎，`AGENT_ENGINE=codex|pi` 可切换。
2. 同一批样本分片分别跑 opencode / codex / pi，比对 `reply` 与产物文件。
3. 记录：事件协议版本、进程资源占用、超长会话表现、provider 切换降级情况。

## verification

- **判据**：Codex/Pi 的 `reply` 与产物文件与 opencode 基线**语义等价**（不要求逐字一致）。
- PoC 前 `AGENT_ENGINE` 恒为 `opencode`；PoC 结论决定何时进入生产。5090 层切引擎只写 `docker-compose.5090.yml`。
