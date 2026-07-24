# route_auth

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/api/routes/auth.py` |
| 层级 | 路由层 |
| 领域 | 权限与审计 |
| 行数 | 75 |

**职责**: 登录鉴权三件套 + 重点客户名录查询。

## Input（输入）— 端点清单（4 个）
| 方法 | 路径 | 请求要点 |
|---|---|---|
| POST | `/api/auth/login` | `{email, password}`，附带 UA/IP 供审计 |
| GET | `/api/auth/me` | `Authorization` header |
| POST | `/api/auth/logout` | `Authorization` header |
| GET | `/api/customers/key-accounts` | 无参，返回除 SEWPG 自身外的客户名录（含别名） |

## Output（输出）
- 登录返回会话 token + user；登录成功/失败均写审计（`audit_service.record`）。

## 调用链
- **上游**: 前端 Login 页与全局请求头。
- **下游**: `auth_service`、`audit_service`、`identity.CUSTOMER_REGISTRY`（客户静态注册表）。

## 中间数据与状态
- 会话 TTL `AUTH_SESSION_TTL_SEC`（默认 24h）；审计记录 action_type=auth。
