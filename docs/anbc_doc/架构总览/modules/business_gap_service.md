# business_gap_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_gap_service.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 大型（商务缺口域的总门面） |

**职责**: 商务标缺口识别与任务处理的唯一门面：检测运行、计划读取（触发运行时终审）、事实表构建/保存、候选素材选择/模板选择/AI 草拟/表格填写/人工上传/产物确认与回灌素材库。

## Input（输入）
- `run_detection(project_id)`：读 S1 交接件（`business_s1_handoff.business_s1_consumption_context`）+ 素材索引。
- 任务操作：task_id + 请求体（素材/模板选择、上传 base64/multipart、AI 草拟参数、表格填写目标）。

## Output（输出）
- 缺口计划（tasks，decision 五态 + `recompute_task_states` 终审）；项目事实表（schema 版本 `PROJECT_FACT_TABLE_SCHEMA_VERSION`）；AI 草拟 docx（`business_gap_ai_draft.write_business_ai_draft_docx`）；表格填写产物（`run_business_table_fill_skill`）；resolvedArtifacts 记录与素材库回灌。

## 调用链
- **上游**: `routes/business_gaps.py`（19 个端点全部经此门面）。
- **下游**: `business_gap_planning`（计划构建/Skill 调用）、`business_gap_domain`（任务/产物领域规则）、`business_gap_state`/`business_gap_repository`（状态与持久化）、`business_gap_fact_table`、`business_gap_table_fill`、`business_gap_refresh`、`business_gap_ai_draft`、`business_bidder_profile`（投标人事实）、`business_s1_handoff`、`business_material_store`、`performance_material_resolver`（业绩素材）、`material_folder_scope`、`minio_client`。

## 中间数据与状态
- 缺口计划运行态（decision：`ready/fill_required/material_required/ai_draft_required/review_required`；status：`needs_input/resolved/...`）；项目事实表；产物文件（workspace 本地 + MinIO）；Skill：`bid-business-gap-planner`、表格填写 Skill。
