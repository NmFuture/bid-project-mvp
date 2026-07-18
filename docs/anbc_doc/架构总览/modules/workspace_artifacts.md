# workspace_artifacts

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/workspace_artifacts.py` |
| 层级 | 服务层 |
| 领域 | 权限与审计 |
| 行数 | 371 |

**职责**: 项目 workspace 目录约定的唯一定义：`documents卷/{projectId}/{technical|business}-workspace/`，含 parse 子目录、stage 工作目录、S1 交接件发布/读取、解析临时承载的转正与清理。

## Input / Output
- `workspace_dir(project_id, bid_type)`、`technical/business_workspace_dir`、`workspace_parse_dir`、`technical_workspace_stage_dir`、`legacy_workspace_roots`（旧目录兼容）。
- `promote_parse_artifacts_to_workspace`（参与决策后临时承载→正式项目）、`cleanup_parse_temp_workspace`（放弃后清理）；S1 交接件按 `business_s1_handoff` 的 schema/status 常量发布。

## 调用链
- **上游**: `bid_runtime_state`、`bid_project_state`、`outline_generation`、`tech_assembly`、两轨 gap/document/wiki 域、`ocr_service`、`onlyoffice_documents`。
- **下游**: `parse_profiles`（workspace 目录名）、`business_s1_handoff`（契约常量）、文件系统。

## 中间数据与状态
- workspace 目录树（toc.json/gaps/stage 产物的物理落点）；临时承载生命周期。
