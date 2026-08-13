---
id: harness-04
scope: Harness / opencode 客户端 + 运维
status: pending
depends-on: [harness-01]
---

# harness-04：会话生命周期回收（短板 4）

> 已由 engine-05（波次 B3）接管，以 engine-* 为准；本文件保留现状证据。

## objective

会话用完即删（DELETE session），并给 `opencode_data` 卷建立清理策略，消除无限增长。

## context

- `docs/anbc_doc/架构总览/05-Harness基建.md` §5 短板 4
- harness-01（会话生命周期模块是本任务落点）
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md`

## path

- harness-01 拆分出的会话生命周期模块
- `code/scripts/`（卷清理脚本）
- `code/docker-compose.yml`（:341、:442 `opencode_data` 卷）

## 现状（2026-08-12 复核证据）

- 客户端只有 `abort_session`（opencode_client.py:834-846，POST `/session/{id}/abort`），无 DELETE session 调用。
- `opencode_data` 卷在 scripts/ 7 个脚本与 entrypoint 中均无清理逻辑，无限增长。

## 改造方案

1. 确认 opencode serve 的会话删除 API（查其版本 1.18.2 的接口；若只有 abort，则 abort + 本地记录 TTL 清单作为替代）。
2. 客户端在终态（succeeded/failed/abort）后回收会话；回收失败只告警不阻断主流程。
3. 卷清理脚本：按 mtime 清理 N 天前的会话数据（N 配置化，默认给保守值如 7 天），挂到现有运维脚本体系；5090/气隙部署文档补一句用法。

## verification

- 跑一轮 AI 动作后确认会话被回收（opencode 侧查询或日志）；清理脚本 dry-run 输出符合预期、不误删进行中会话数据。
