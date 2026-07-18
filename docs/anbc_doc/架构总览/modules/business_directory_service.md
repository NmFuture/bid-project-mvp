# business_directory_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_directory_service.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 11 |

**职责**: 商务标目录服务——`BidDirectoryService` 的空壳子类实例，仅绑定 `business_project_service` 与 URL 前缀 `/api/business/projects`。全部逻辑在 `bid_directory_flow`。

## Input / Output
- 同 `bid_directory_flow`（生成状态、run、outline 读写确认、tender-files 预览）。

## 调用链
- **上游**: `routes/business.py` 目录端点组。
- **下游**: `bid_directory_flow.BidDirectoryService`、`bid_project_service.business_project_service`。

## 中间数据与状态
- 无自有状态。
