---
id: harness-06
scope: Harness / opencode 客户端
status: done
depends-on: [harness-01]
---

# harness-06：客户端异步化（短板 6）

> 已由 engine-03（波次 B1）接管，以 engine-* 为准；本文件保留现状证据。

## objective

把 opencode_client 从「同步 httpx.Client + 每会话 daemon 线程轮询」改为 async（httpx.AsyncClient + asyncio 任务），消除 daemon 线程静默死亡的竞态。

## context

- `docs/anbc_doc/架构总览/05-Harness基建.md` §5 短板 6
- harness-01（拆分后的模块边界是本任务的落点）
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md`

## path

- harness-01 拆分出的会话/轮询模块
- 全部调用方：`parsing.py`（S1 分片 ThreadPoolExecutor）、`outline_generation.py`、business/technical AI 类服务、`redis_worker.py`

## 现状（2026-08-12 复核证据）

- 同步 `httpx.Client`（opencode_client.py:68、:141 等）+ 每会话一个 daemon 线程轮询（:1117-1119 `threading.Thread(..., daemon=True)`），在 async FastAPI 里靠线程池消化。
- daemon 线程静默死亡的竞态已被实战踩过（05 文档记录）。

## 改造方案

1. 客户端核心改 `httpx.AsyncClient`，轮询改 asyncio Task（可取消、异常显式传播，不再静默死亡）。
2. 调用方分两批迁移：FastAPI 路由/service 链天然 async 直接迁；worker 与 S1 分片的 ThreadPoolExecutor 场景用 `asyncio.run`/事件循环封装过渡，不强行一次改完。
3. 保留同步 facade 直到调用方全部迁完，避免大爆炸式切换。

## 连带注意

- 与 harness-02 的并发预算联动：异步化后信号量改 `asyncio.Semaphore`，两任务要在同一版并发模型上对齐。
- 失败要显式暴露（根 AGENTS.md）：轮询任务异常必须传到调用方，禁止 try/except 吞掉。

## verification

- 并发压测冒烟：多会话并行时无线程泄漏（前后对比 `threading.enumerate()`/任务数）；取消路径（abort/取消解析）行为不变。
