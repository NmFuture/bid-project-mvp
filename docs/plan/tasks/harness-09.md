---
id: harness-09
scope: Harness / Skill 注册机制
status: done
depends-on: []
---

# harness-09：Skill 运行时注册，加 skill 免改镜像（短板 9）

## objective

命令别名从「构建期 Dockerfile printf 固化」改为运行时生成/注册，新增 skill 不再需要改 Dockerfile 重建镜像。

## context

- `docs/anbc_doc/架构总览/05-Harness基建.md` §1 组成总表、§5 短板 9
- `code/sewpg-bid-backend/opencode/skills/STAGES.md`（别名事实源，harness-11 补全后两轨齐全）
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md`

## path

- `code/sewpg-bid-backend/opencode/Dockerfile`（:37-165 printf 固化的 16 个 wrapper、:30 `COPY .opencode`）
- `code/sewpg-bid-backend/opencode/docker-entrypoint.sh`
- `code/sewpg-bid-backend/opencode/skills/`（各 skill 的 `scripts/run_from_manifest.py` 受控入口）

## 现状（2026-08-12 复核证据）

- 16 个命令别名 wrapper 在构建期由 Dockerfile printf 逐条生成，且内嵌子命令白名单。
- 加一个 skill = 改 Dockerfile + 重建镜像 + 重新部署，迭代成本高。

## 改造方案

1. wrapper 生成逻辑下沉到 `docker-entrypoint.sh`：启动时扫描 `skills/` 目录（或读 STAGES.md/一张注册表），动态生成命令别名与子命令白名单。
2. 或更简：做一个统一分发别名（如 `bidrun <skill> <subcommand>`），白名单从 skills 目录推导——实施时二选一，以「不降低现有权限收紧度」为前提（opencode.json 的 bash allow 语义不能放宽）。
3. 保留构建期镜像内 skill 内容不变（COPY 照旧），本任务只改注册方式。

## 连带注意

- 与 harness-11 协同：商务轨别名表先在 STAGES.md 落地，注册机制直接消费它。
- 权限模型是安全面：entrypoint 生成逻辑要把「不在注册表里的命令拒绝」作为默认分支。

## verification

- 新增一个 dummy skill 目录，不改 Dockerfile、重启容器后别名可用；未注册命令被拒绝。
