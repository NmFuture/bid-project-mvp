---
id: harness-01
scope: Harness / opencode 客户端
status: ready
depends-on: []
---

# harness-01：opencode_client 拆分 + early_tool_command 注册机制（短板 1）

## objective

把 2817 行的 `opencode_client.py` 按职责拆成模块；业务命令特判（early_tool_command）从硬编码 if 链改为注册表，新增 agent 任务不再改公共客户端。

## context

- `docs/anbc_doc/架构总览/05-Harness基建.md` §3 调用链、§5 短板 1
- `docs/anbc_doc/架构总览/modules/opencode_client.md`（行数已更正 2817）
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md`（波次 2 主线，本任务是 06/03/04 的前置）

## path

- `code/sewpg-bid-backend/app/services/opencode_client.py`（拆分原点）
- 新模块建议放 `app/services/opencode_client/` 包或 `app/services/opencode_*.py` 同级文件
- 业务命令注册方：`parsing.py`、`outline_generation.py`、`technical_fact_curator.py`、`business_*` 等调用方
- 同步更新 `modules/opencode_client.md` 卡片与 `_data/bid_parse.json`

## 现状（2026-08-12 复核证据）

- 全文 2817 行且仍在增长；30+ 处 `early_tool_command="..."` 字面量。
- 业务特判硬编码：`:1179-1224` 对 `s1parse-finalize`/`btplnav-finalize`/`s2outline-finalize` 分支；`:1217-1221` factcurate「不提前返回」特判；`:1486`/`:1499`/`:2072-2074` 按命令名分发 stalled trace 与校验。
- 每加一类 agent 任务都要改这个公共文件，回归高发。

## 改造方案

1. 按职责拆分（建议四块，可实施时微调）：
   - 会话生命周期（create/abort/poll）
   - 轮询监管与提前完成判定引擎（通用状态机，不识业务命令）
   - 返回解析与 JSON 修复（`_repair_json_payload` 等）
   - 对外门面 `OpencodeClient`（保持现有调用方签名不变）
2. 定义命令注册表：`{命令名: {提前完成判定, stall 策略, 结果校验}}`，业务模块（parsing/outline/factcurate/business）在自己的代码里注册，客户端引擎查表执行。
3. **行为零变化**是本任务的底线：先加表征测试（characterization test）锁定现有提前完成/轮询/修复行为，再拆。

## 连带注意

- 与 harness-02/05/07 都碰这个文件，按波次串行合入；本任务是波次 2 第一步。
- 拆分后模块卡片与 _data 的 loc/调用链要同步。

## verification

- 表征测试 + 现有 opencode 相关测试全绿；技术/商务两轨各跑通一次 AI 动作（目录生成或解析）冒烟。
