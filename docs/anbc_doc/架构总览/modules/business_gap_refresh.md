# business_gap_refresh

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_gap_refresh.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 156 |

**职责**: 缺口计划的运行时刷新器：每次读取计划时同步模板候选（项目上传模板出现/失效时增删 templateCandidates）与素材类型标签，并触发任务状态重算。

## Input / Output
- Input: 项目 dict + business_gap_state（plan.tasks）。
- Output: 原地更新任务的 `templateCandidates`（按 templateId/filePath 认领，sourceMode=project_uploaded_bid_template 优先）、businessMaterialKind 标签；返回是否变更。

## 调用链
- **上游**: `business_gap_service`（gaps 读取路径）。
- **下游**: `business_gap_domain`（重算任务）、`business_gap_planning`（模板索引/素材索引）、`workspace_artifacts`（gaps 工作目录）。

## 中间数据与状态
- `business_gap_state.plan.tasks[].templateCandidates`；workspace `gaps/` 模板索引。
