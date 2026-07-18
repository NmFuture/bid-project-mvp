# project_stage_flow

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/project_stage_flow.py` |
| 层级 | 服务层 |
| 领域 | 项目与状态流 |
| 行数 | 193 |

**职责**: 项目阶段流的唯一定义（`STAGE_SCHEME="S0_S6"`，阶段 1-6）：双轨阶段命名（技术：模板与目录/审核目录/缺口处理/生成标书/共创/导出；商务：素材匹配与共创导出合并组）、人机分工标记（isHuman）、阶段归一化与推进规则、目录确认联动推阶段。

## Input / Output
- `normalize_project_stage_value`、`updated_project_stage_after_request`、`apply_confirmed_outline_stage`、`project_progress_stages`（进度组视图）、`should_skip_technical_gap_stage`。

## 调用链
- **上游**: `bid_project_state`、`bid_outline_state`、`bid_parse_state`。
- **下游**: `bid_type`、`turbine_models`。

## 中间数据与状态
- 阶段常量组（TECHNICAL/BUSINESS_STAGE_PROGRESS_GROUPS）；`MAX_PROJECT_STAGE=6`。与前端 `*StageFlow.js` 的路由映射一一对应。
