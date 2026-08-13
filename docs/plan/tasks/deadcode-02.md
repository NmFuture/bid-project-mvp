---
id: deadcode-02
scope: Harness / opencode Skill 库
status: ready
depends-on: []
---

# deadcode-02：删除遗留 Skill bid-draft-sections-json

## objective

删除 `code/sewpg-bid-backend/opencode/.opencode/skills/bid-draft-sections-json/`，消除「疑似未清理旧物」。

## context

- `docs/anbc_doc/架构总览/05-Harness基建.md` §2（遗留记录处，删除后同步该段）
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md`

## path

- `code/sewpg-bid-backend/opencode/.opencode/skills/bid-draft-sections-json/`
- `docs/anbc_doc/架构总览/05-Harness基建.md`（删除后去掉对应遗留说明）

## 现状（2026-08-12 复核证据）

- 该目录仍在，且只剩一个 1448 字节的 `SKILL.md`，无任何脚本。
- 代码库中除其自身外零引用。
- 它会被 `opencode/Dockerfile:30` 的 `COPY .opencode` 带进镜像，属于无谓的镜像内容。

## 改造方案

1. 再次全仓 grep `bid-draft-sections-json`（含 `opencode/`、`app/`、`code/scripts/`、compose、前端）确认零引用。
2. 删除整个目录。
3. 更新 `05-Harness基建.md` §2 的遗留说明。

## verification

- grep 零命中（除历史文档）。
- 构建 opencode 镜像或至少确认 Dockerfile 无对该路径的显式引用；compose 起 opencode 服务健康检查通过。
