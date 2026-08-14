---
id: harness-10
scope: Harness / 部署运维
status: done
depends-on: []
---

# harness-10：opencode-auth 自举（短板 10）

## objective

让新环境能自举 opencode 鉴权承载：恢复 `code/opencode-auth/` 目录占位、写清 auth.json 的来源/格式/生成方式。

## context

- `docs/anbc_doc/架构总览/05-Harness基建.md` §1 组成总表、§5 短板 10
- 关联：harness-05（端口鉴权）实施时 auth.json 才是必需品，本任务先把载体与文档补齐
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md`

## path

- `code/opencode-auth/`（新建 README + `.gitkeep`；**不放真实 auth.json**，真实凭证禁止提交）
- `code/sewpg-bid-backend/opencode/docker-entrypoint.sh`（:7-9 现有拷贝逻辑，仅作说明对象，非必须改）
- `code/.env.example`（:68 `OPENCODE_AUTH_HOST_DIR` 裸变量，说明补全）

## 现状（2026-08-12 复核，2026-08-14 刷新引用）

- `code/opencode-auth/` 已不在仓库（git 不跟踪空目录），但 `docker-compose.yml:349` 仍默认挂载 `./opencode-auth`（`${OPENCODE_AUTH_HOST_DIR:-./opencode-auth}`）。
- auth.json 仅有 entrypoint 的拷贝逻辑（:7-9）和 `.env.example:68` 一个裸变量；来源/格式/生成方式无文档，新环境无法自举。

## 改造方案

1. `code/opencode-auth/README.md`：说明 auth.json 的格式（opencode serve 的鉴权文件）、获取/生成方式（从 LLM 网关控制台导出或手工按模板生成）、放置路径、以及它是运行时挂载点不入库。
2. 加 `.gitkeep` 恢复目录跟踪；README 中给出脱敏模板。
3. `.env.example` 相关变量补一行中文说明。

## verification

- 按 README 在干净环境走一遍挂载流程，opencode 容器能正常启动（entrypoint 拷贝逻辑不报错）。
