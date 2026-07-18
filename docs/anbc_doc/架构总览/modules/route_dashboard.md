# route_dashboard

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/api/routes/dashboard.py` |
| 层级 | 路由层 |
| 领域 | 系统 |
| 行数 | 17 |

**职责**: 单端点 `GET /api/dashboard`：按当前登录用户构建工作台数据。

## Input / Output
- Input: `Authorization` header → `auth_service.me` 解析用户。
- Output: `dashboard_service.build(user)` 的工作台汇总结构。

## 调用链
- **上游**: 前端 Dashboard 页。
- **下游**: `auth_service`、`dashboard_service`。

## 中间数据与状态
- 无自有状态。
