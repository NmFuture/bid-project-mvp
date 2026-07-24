# bid_type

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/bid_type.py` |
| 层级 | 服务层 |
| 领域 | 项目与状态流 |
| 行数 | 42 |

**职责**: 标类常量与归一化的唯一定义：`技术标` / `商务标` / `通用`。双轨隔离的类型基石。

## Input / Output
- `normalize_bid_type(value)`：任意文本 → 标准标类（含「商务/技术」子串模糊归一）。
- `require_bid_type(value, allow_general=False)`：非法值抛 ValueError（fill_generation job 必须显式绑定标类即靠它把关）。
- `is_business_bid_type` / `is_technical_bid_type` 判别函数。

## 调用链
- **上游**: 路由与两轨 service 广泛使用（如 `redis_worker`、`business.py` 路由上传素材时固定 `BUSINESS_BID_TYPE`）。
- **下游**: 无。

## 中间数据与状态
- 常量集合 `BID_TYPES = {技术标, 商务标, 通用}`。
