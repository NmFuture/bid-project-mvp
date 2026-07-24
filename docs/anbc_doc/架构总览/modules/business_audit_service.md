# business_audit_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_audit_service.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 30 |

**职责**: 商务标审计门面：给 `audit_service` 的查询强制注入 `bidType=商务标` 过滤，detail 校验归属（非商务标记录 404）。

## Input / Output
- Input: 查询过滤参数、audit_id。
- Output: 审计列表/导出/详情（跨轨访问返回 `BUSINESS_AUDIT_NOT_FOUND`）。

## 调用链
- **上游**: `routes/business.py` `/api/business/audit*`。
- **下游**: `audit_service`、`bid_type`、`peripheral`。

## 中间数据与状态
- 无自有状态；审计数据在 `audit_service` 侧。
