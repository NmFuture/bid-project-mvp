# technical_gap_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_gap_service.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 大型（技术缺口域总门面） |

**职责**: 技术标缺口域的唯一门面 `TechnicalGapService`：检测运行、计划读取（含终审 `recompute_technical_gap_decisions`）、事实表、素材选择/人工上传/AI 填写（单条与 ai_fill_all）、产物确认、提交评审、缺料台账。

## Input（输入）
- `run_detection(project_id)`：目录 toc + 附表任务 + 素材索引。
- 任务操作：gap_id + 请求体；`ai_fill(_all)` 过滤条件 `decision == fill_required`。

## Output（输出）
- 缺口计划（items：decision `ready/fill_required/review_required/material_required`，appendixTasks/fillTasks/candidateMaterials/resolvedArtifacts）；填写质量聚合（`aggregate_technical_gap_fill_quality`，qualityStatus）；项目事实表（确认状态 `confirmed`）；评审文档状态。

## 调用链
- **上游**: `routes/technical.py` 缺口端点组（gaps-detection、gaps、facts、submissions 等）。
- **下游**: `technical_gap_actions`（计划构建 + 填写执行，Skill：`TECHNICAL_TABLE_FILL_SKILL_NAME`/`TECHNICAL_WORD_FILL_SKILL_NAME`）、`technical_gap_domain`（终审/汇总/完整性检查）、`technical_gap_state`/`technical_gap_repository`（状态与持久化）、`technical_gap_fact_table`、`material_folder_scope`、`url_utils`。

## 中间数据与状态
- 缺口计划运行态；fillTasks/appendixTasks 完成状态；`PROJECT_FACT_CONFIRMED_STATUSES={"confirmed"}`；异常映射同商务（400/404/PeripheralError）。
