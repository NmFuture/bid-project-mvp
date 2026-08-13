---
id: engine-03
scope: AgentEngine / OpencodeEngine 异步化
status: pending
depends-on: [engine-01]
---

# engine-03（波次 B1，对应 harness-06）：OpencodeEngine 异步化

## objective

把引擎从「同步 httpx.Client + 每会话 daemon 线程轮询」改为 async（httpx.AsyncClient + asyncio 任务），消除 daemon 线程静默死亡的竞态；`AgentEngine` 协议同步翻成方案 §3 的 async 目标形态。

## context

- `docs/20260813-AgentEngine多内核引擎改造方案.md` §3、§6 波次 B1
- `docs/plan/tasks/harness-06.md`（现状证据与调用方清单以其为准）
- engine-01 产出（`agent_engine/` 包）；若 engine-02 已合入，基于其回调机制改造

## path

- `code/sewpg-bid-backend/app/services/agent_engine/`（引擎与协议）
- 全部调用方：`parsing.py`（S1 分片 ThreadPoolExecutor）、`outline_generation.py`、business/technical AI 类服务、`redis_worker.py`

## 现状

- 同步 `httpx.Client` + 每会话一个 daemon 线程轮询（原 opencode_client.py:1117-1119 `threading.Thread(..., daemon=True)`），在 async FastAPI 里靠线程池消化；daemon 线程静默死亡的竞态已被实战踩过（05-Harness基建.md 记录）。

## 改造方案

1. 协议方法改 async；`OpencodeEngine` 内部换 `httpx.AsyncClient`，轮询改 asyncio task。
2. 调用方逐个适配（同步上下文用 `asyncio.run` 之外的项目既有桥接模式，遵循现有代码约定）。
3. 行为保持：heartbeat、idle 超时、进度增量语义不变。

## verification

- 与 CI 对齐后端测试全绿，失败集合与基线比对不得新增；并发冒烟（S1 分片并行）在 dev 环境验证。
