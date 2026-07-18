# technical_gap_domain

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_gap_domain.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 297 |

**职责**: 技术缺口领域规则纯函数库，核心是**决策终审** `recompute_technical_gap_decisions`（对齐商务标两层架构）与 S7 放行判定 `technical_gap_artifact_is_s7_ready`。

## 终审优先级（每次读取重跑）
1. 有非 AI 的可用产物（人工上传/选材）→ `ready/resolved`
2. 有未放行的 AI 产物 → `review_required`（须验收或人工确认）
3. 有未完成 fillTasks → `fill_required`
4. 任务全完成且有可合并 AI 产物 → `ready`
5. 初判 fill_required 但只剩 candidateMaterials → 改判 `review_required`
6. 其余保持初判（ready/structural/material_required 不误伤）

S7 放行：`s7Ready!=false` 且（非 ai_fill 来源 / qualityGate=human_confirmed / qualityReport.status=passed）。

## Input / Output
- Input: 缺口计划 plan（items[]）。Output: 改写 decision/status 的条目数；计划摘要/完整性检查/产物 OnlyOffice payload/填写质量聚合。

## 调用链
- **上游**: `technical_gap_service`、`technical_gap_state`、`technical_gap_planner`、`tech_assembly`（S7 过滤）、`technical_gap_ai_fill`、`technical_gap_review`。
- **下游**: 无服务依赖（纯函数）。

## 中间数据与状态
- 计划结构（items[].decision/status/resolvedArtifacts/fillTasks/candidateMaterials/qualityGate）。
