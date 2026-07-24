# technical_gap_planner

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_gap_planner.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 786 |

**职责**: 技术缺口计划构建引擎：准备 manifest（素材范围/机型/附表来源矩阵），运行 Skill `bid-tech-gap-planner` 产出初判计划（schema `bid-tech-gap-plan-v1`），再挂确定性后处理（证据片段召回、主题召回、**决策终审**）。

## Input（输入）
- 项目 dict（toc、素材范围 `build_project_material_scope`、机型 `project_turbine_model`）、附表来源矩阵（`technical_appendix_source_matrix`）。
- 片段召回复用 planner Skill 脚本函数（importlib 同源加载，失败整体跳过不阻断）。

## Output（输出）
- 缺口计划（items：decision/candidateMaterials/fillTasks/appendixTasks/evidenceSegments）；fillTask Skill 名归一（table-filler / word-placeholder-filler）；计划摘要。

## 调用链
- **上游**: `technical_gap_actions`（build 入口）、`technical_gap_state`、`technical_material_index`。
- **下游**: Skill `bid-tech-gap-planner`（subprocess）、`technical_gap_domain`（终审）、`technical_appendix_source_matrix`、`technical_material_store`、`opencode_client`、`identity`、`turbine_models`、`workspace_artifacts`。

## 中间数据与状态
- technical workspace stage 目录（manifest/计划文件）；Skill 常量：`bid-tech-table-filler`、`bid-tech-word-placeholder-filler`。
