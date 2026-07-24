# technical_audit_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_audit_service.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 30 |

**职责**: 技术标审计门面：查询强制注入 `bidType=技术标`，detail 归属校验（跨轨 404 `TECHNICAL_AUDIT_NOT_FOUND`）。与 business_audit_service 完全对称。

## 调用链
- **上游**: `routes/technical.py` `/api/technical/audit*`。
- **下游**: `audit_service`、`peripheral`。

## 中间数据与状态
- 无自有状态。
