# business_gap_planning

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_gap_planning.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 1459 |

**职责**: 商务缺口计划的构建引擎：准备 manifest（S1 消费上下文、素材/模板/Wiki/业绩/事实表/机型），运行 Skill `bid-business-gap-planner` 产出计划（schema `bid-business-gap-plan-v1`），并提供素材选择器索引、表格填写 Skill 调用（`bid-business-table-fill`）与产物 URL 刷新。

## Input（输入）
- 项目 dict（S1 交接件消费上下文 `business_s1_consumption_context`）、素材库（`business_material_store`）、Wiki（`WikiDoc/WikiNode` 表）、业绩库（`performance_package_service`）、投标人档案、模板回退（`template_store`）、机型（`turbine_models`）。

## Output（输出）
- 缺口计划（tasks/tocRefs/candidateMaterials/templateCandidates，schema v1）；素材选择器索引 `build_business_gap_material_picker_index`；表格填写结果（schema `bid-business-table-fill-v1`）；计划摘要 `summarize_business_gap_plan`。

## 调用链
- **上游**: `business_gap_service`、`business_gap_state/refresh/table_fill`、`business_assembly`。
- **下游**: Skill `bid-business-gap-planner`/`bid-business-table-fill`（subprocess run_from_manifest.py，兼容 skills/ 与旧 skill/ 目录）、`business_s1_handoff`、`business_gap_fact_table`、`business_material_store`、`performance_package_service`、`opencode_client`、`minio_client`、`template_store`、`workspace_artifacts`。

## 中间数据与状态
- workspace `gaps/` 工作目录（manifest/计划文件）；DB `wiki_docs`/`wiki_nodes`（Wiki 输入）；计划 schema 版本常量。
