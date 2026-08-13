---
id: harness-02
scope: Harness / 并发治理
status: ready
depends-on: []
---

# harness-02：并发治理统一（短板 2）

## objective

消除三个互不知晓的信号量池造成的「实际并发=各池之和」；章节并行度配置化；代码默认值与 compose 默认值对齐。

## context

- `docs/anbc_doc/架构总览/05-Harness基建.md` §3 并发入口、§5 短板 2
- 根 AGENTS.md 配置分层规则（代码默认值必须本地安全，5090 取值只写 `docker-compose.5090.yml`）
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md`

## path

- `code/sewpg-bid-backend/app/services/opencode_client.py`（:24 `_OPENCODE_REQUEST_SLOTS`）
- `code/sewpg-bid-backend/app/services/parsing.py`（:6355 `_S1_SHARD_REQUEST_SLOTS`，默认 7）
- `code/sewpg-bid-backend/app/services/outline_generation.py`（:45-47 章节 6+1 硬编码、`_TECH_OUTLINE_REQUEST_SLOTS`）
- `code/sewpg-bid-backend/app/core/config.py`（:245 `OPENCODE_MAX_CONCURRENCY` 默认 8）
- `code/docker-compose.yml`（:44 fastapi、:141 worker 均为 `:-1`）
- `code/docker-compose.5090.yml`（5090 实测取值写这里）

## 现状（2026-08-12 复核证据）

- 三个信号量池互不知晓：全局 8 + S1 分片 7 + 目录章节 6+1，实际并发是各池之和。
- 代码默认 `OPENCODE_MAX_CONCURRENCY=8`（config.py:245）与 compose 默认 1 恰好相反，本地不起 compose 层时并发直接 8。
- `TECH_OUTLINE_CHAPTER_WORKERS = 6` 硬编码，compose 未暴露该变量。

## 改造方案

1. 定义**单一并发预算**：一个总的 opencode 并发上限，S1 分片/目录章节从中分配（或至少三池共享一个预算常量并互相感知）；选型在实施时定，但「各池之和不受控」必须消除。
2. `OPENCODE_MAX_CONCURRENCY`、S1 分片并发、章节并行度全部做成配置项（DB 系统设置 → 环境变量回退的现有链路），**代码默认值取本地安全值（建议 1~2）**，与 compose 默认对齐；5090 实测取值写进 `docker-compose.5090.yml`，不动代码默认。
3. 删掉「6+1」魔法数，章节数与并行度分离。

## 连带注意

- 并发正确性（锁、断点续跑）用 mock 在 Dev 即可验证，不依赖 GPU（根 AGENTS.md 已明确）。
- 改完要确认技术/商务两轨的解析、目录生成、填写链路并发行为不退化。

## verification

- 后端测试覆盖并发限制相关用例；本地默认配置下起服务，观察 opencode 并发峰值 ≤ 预算。
