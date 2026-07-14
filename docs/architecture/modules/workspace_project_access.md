# workspace_project_access

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/workspace_project_access.py` |
| 层级 | 服务层 |
| 领域 | 权限与审计 |
| 行数 | 中型 |

**职责**: 双轨工作区的项目访问守门员：读取/更新项目运行态时强校验标类归属（技术标项目不能被商务轨访问，反之亦然），并提供跨轨中性读取（worker 用）。

## Input（输入）
- `project_id` + 期望 `bid_type` + 错误工厂（not_found/wrong_type，各轨映射为自己的 404/403 语义）。

## Output（输出）
- 项目运行态 dict（`store.get_project_runtime_state`）；`get_any_workspace_project_runtime_state`（不校验标类，redis_worker/中性 flow 使用）；`persist_workspace_project_state` 持久化；`list_workspace_projects` 过滤分页（status/bidType/reviewDecision/dateRange）。

## 调用链
- **上游**: `bid_directory_flow`、`bid_generation_flow`、`bid_document_flow`、`bid_parse_service`、`redis_worker`、两轨 service。
- **下游**: `store`、`bid_type`、`bid_project_state`、`bid_parse_state`。

## 中间数据与状态
- 无自有状态；是「双轨互不越界」规约在数据访问层的落点。
