---
id: harness-08
scope: Harness / 配置治理
status: ready
depends-on: []
---

# harness-08：模型回退逻辑单点化（短板 8）

## objective

把 `big-pickle → deepseek-v4-flash` 的模型映射从 4 处收敛为 1 处事实源，其余处引用。

## context

- `docs/anbc_doc/架构总览/05-Harness基建.md` §5 短板 8
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md`

## path

- `code/sewpg-bid-backend/app/core/config.py`（:10 默认模型、:17-18 映射）
- `code/sewpg-bid-backend/opencode/docker-entrypoint.sh`（:24-36 runtime 改写、:66-69 INTERNAL_LLM 分支、:138-141 legacy 分支）
- `code/docker-compose.yml`（:307-308 默认值）

## 现状（2026-08-12 复核证据）

- 同一映射散在 4 处：config.py:17-18 + entrypoint 三处（:24-36、:66-69、:138-141），新增/更换模型要同步改多处，漏改即行为分裂。
- 当前默认模型已是 `deepseek/deepseek-v4-flash`（config.py:10、compose:307-308、entrypoint 两分支默认一致），文档已更正。

## 改造方案

1. 在 entrypoint 内定义一个 `resolve_model_id()` shell 函数（或生成一份 runtime.json 模板），三个分支统一调用；Python 侧 config.py 保留同名映射常量并注释「与 entrypoint 互为镜像，改动需同步」——或更进一步：entrypoint 把解析后的模型写入固定文件/环境变量，Python 侧直接读取，做到真正单点。
2. 优先做「entrypoint 内部单函数化」这半步，风险最小；完全单点（跨 shell/python）若侵入大，记录到 backlog。

## verification

- 分别走 runtime.json / INTERNAL_LLM / legacy 三条配置链启动 opencode，解析出的模型一致；big-pickle 入参正确映射。
