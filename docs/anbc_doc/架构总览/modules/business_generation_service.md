# business_generation_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_generation_service.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 11 |

**职责**: 商务标正文生成服务——`BidGenerationService` 的空壳子类实例，绑定 `business_project_service` 与 `/api/business/projects` 前缀。逻辑全在 `bid_generation_flow`。

## Input / Output
- 同 `bid_generation_flow`（status / run 入队 fill_generation）。

## 调用链
- **上游**: `routes/business.py` fill-generation 端点。
- **下游**: `bid_generation_flow.BidGenerationService`、`bid_project_service`。

## 中间数据与状态
- 无自有状态。
