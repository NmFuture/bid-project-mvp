# technical_directory_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_directory_service.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 11 |

**职责**: 技术标目录服务——`BidDirectoryService` 空壳子类实例，绑定 `technical_project_service` 与 `/api/technical/projects` 前缀。逻辑全在 `bid_directory_flow`（含 SSE 流）。

## 调用链
- **上游**: `routes/technical.py` 目录端点组。
- **下游**: `bid_directory_flow`、`bid_project_service`。

## 中间数据与状态
- 无自有状态。
