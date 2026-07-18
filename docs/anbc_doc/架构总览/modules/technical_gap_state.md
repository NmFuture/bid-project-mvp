# technical_gap_state

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_gap_state.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 89 |

**职责**: 技术缺口运行态 `gap_state` 的结构保障：默认字段注入、fillTask Skill 名修复迁移、从计划生成 legacy items 视图（跳过 matched/structural）。

## Input / Output
- Input: 项目 dict / 计划。
- Output: `gap_state`：`{recognitionStatus: idle→…, recognizedAt, submittedForReview, reviewConfirmed, reviewedAt, items, submissions, plan, planFile, integrity, projectFactTable}`；评审文档默认态 `ensure_technical_review_document_state`。

## 调用链
- **上游**: `technical_gap_service`、`technical_gap_actions`、`tech_assembly`、`technical_gap_review`、`technical_gap_ai_fill`。
- **下游**: `technical_gap_domain`（完整性）、`technical_gap_planner`（Skill 名归一）、`store`。

## 中间数据与状态
- `gap_state` 全字段（项目 JSONB 内）；legacy items 兼容视图。
