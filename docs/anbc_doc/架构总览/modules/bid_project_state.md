# bid_project_state

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/bid_project_state.py` |
| 层级 | 服务层 |
| 领域 | 项目与状态流 |
| 行数 | 548 |

**职责**: 项目实体状态的纯函数集：创建/更新/删除副作用、身份归一化（客户/编码/日期/机型）、参与决策、阶段推进、各运行态默认值注入——项目 JSON 文档的「schema 守护者」。

## Input（输入）
- 项目 dict + 前端更新请求；`reviewDecision ∈ {pending 待审核, participate 参与投标, abandon 不参与}`。

## Output（输出）
- 归一化后的项目：currentStage（`project_stage_flow.STAGE_SCHEME`）、projectCode、start/endDate/deadline、identity（客户 id/规范名，经 `identity.build_project_identity`）、素材空间、机型明细（`turbine_models` 归一化）；解析临时承载转正（`workspace_artifacts.promote_parse_artifacts_to_workspace`）与删除清理（`cleanup_parse_temp_workspace`）。

## 调用链
- **上游**: `store`（加载归一化）、`workspace_project_access`、`bid_parse_service`、`bid_directory_flow`、`outline_generation`、`tech_assembly`。
- **下游**: `bid_fill_state`/`bid_parse_state`（默认运行态）、`bid_runtime_state`、`bid_type`、`identity`、`project_stage_flow`、`turbine_models`、`workspace_artifacts`、`file_utils`、`peripheral`。

## 中间数据与状态
- 项目字段全集（存 `projects` 表 JSONB）；`reviewDecision` 三态；`stageScheme` + `currentStage`；`should_skip_technical_gap_stage` 等阶段特例规则。
