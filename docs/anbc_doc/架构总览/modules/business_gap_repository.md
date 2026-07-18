# business_gap_repository

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_gap_repository.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 39 |

**职责**: 商务缺口域的项目访问薄层：读/写商务标项目运行态，标类不符时抛 `BUSINESS_PROJECT_REQUIRED`(400)、不存在抛 `BUSINESS_PROJECT_NOT_FOUND`(404)。

## Input / Output
- Input: project_id / 项目 dict。
- Output: 项目运行态；`persist_business_gap_project` 持久化。

## 调用链
- **上游**: `business_gap_service`。
- **下游**: `workspace_project_access`、`peripheral`、`bid_type`。

## 中间数据与状态
- 无自有状态。
