# route_system

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/api/routes/system.py` |
| 层级 | 路由层 |
| 领域 | 系统 |
| 行数 | 43（3 个端点） |

**职责**: 健康检查：`GET /healthz`（容器 healthcheck 用）、`GET /api/healthz`、`GET /api/root`。

## Input / Output
- 无参；返回服务状态与关键路径/后端配置回显（store backend、目录、opencode/onlyoffice 地址）。

## 调用链
- **上游**: docker healthcheck、运维探活。
- **下游**: `core.config`。

## 中间数据与状态
- 无。
