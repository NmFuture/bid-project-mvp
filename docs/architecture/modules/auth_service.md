# auth_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/auth_service.py` |
| 层级 | 服务层 |
| 领域 | 权限与审计 |
| 行数 | 277 |

**职责**: 认证与用户管理：pbkdf2_sha256（26 万次迭代）口令散列、Bearer 会话（TTL 24h）、启动引导管理员、用户 CRUD、`current_user` FastAPI 依赖。

## Input / Output
- `login(email, password, ua, ip)` → token+user；`me/logout(authorization)`；`list/create/update_user`；`ensure_bootstrap_admin()`（AUTH_ADMIN_* 环境变量）。
- 鉴权失败抛 HTTPException 401。

## 调用链
- **上游**: `route_auth`、`route_settings`、`route_dashboard`、各需登录端点的 `Depends(current_user)`、`app_main`（启动引导）。
- **下游**: DB `SystemUser`/`AuthSession`、`material_runtime_tables`、`core.config`。

## 中间数据与状态
- `system_users`/`auth_sessions` 表；会话 token（secrets 随机）与过期时间。
