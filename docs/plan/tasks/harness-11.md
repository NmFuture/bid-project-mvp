---
id: harness-11
scope: Harness / Skill 命名体系
status: ready
depends-on: []
---

# harness-11：STAGES.md 补商务轨映射（短板 11）

## objective

在 `opencode/skills/STAGES.md` 追加商务轨的「用户阶段 ↔ 命令别名 ↔ 历史工作目录编号」映射表，消除商务别名只散在 Dockerfile 里的状态。

## context

- `code/sewpg-bid-backend/opencode/skills/STAGES.md`（现 24 行，只覆盖技术轨；:24 自述「商务标如需同样映射，在本文件追加第二张表」）
- `code/sewpg-bid-backend/opencode/Dockerfile`（:37-165 printf 固化的商务别名 wrapper：btplnav/businessgap/businessassemble 等）
- `docs/anbc_doc/架构总览/05-Harness基建.md` §5 短板 11
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md`

## path

- `code/sewpg-bid-backend/opencode/skills/STAGES.md`
- `docs/anbc_doc/架构总览/05-Harness基建.md`（短板 11 标记修复）

## 现状

- 商务轨 8 个 Skill（bid-business-tender-structured-parser / outline-generator / gap-planner / table-fill / assembler / format-cleaner / template-extractor / wiki-material-builder）的命令别名只在 Dockerfile printf 里，无统一映射表；阶段命名、别名与历史工作目录编号的对应关系技术轨有、商务轨无。

## 改造方案

1. 从 Dockerfile wrapper 与商务轨 service 调用点（`business_gap_planning.py`、`business_assembly.py` 等）收集全部商务别名。
2. 按技术轨表的同格式追加商务轨映射表。
3. 根 AGENTS.md 约定「阶段命名、命令别名与历史工作目录编号的对应关系统一引用 STAGES.md」——补完后商务轨 SKILL.md 里如有各自解释处，改为引用 STAGES.md。

## verification

- 表中每个别名都能在 Dockerfile 或 skill 脚本中找到对应；技术轨表不被改动。
