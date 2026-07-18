# technical_generation_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_generation_service.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 11 |

**职责**: 技术标正文生成服务——`BidGenerationService` 空壳子类实例，绑定技术轨。逻辑全在 `bid_generation_flow`。

## 调用链
- **上游**: `routes/technical.py` fill-generation 端点。
- **下游**: `bid_generation_flow`、`bid_project_service`。

## 中间数据与状态
- 无自有状态。
