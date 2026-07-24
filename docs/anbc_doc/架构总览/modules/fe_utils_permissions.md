# fe_utils_permissions

| | |
|---|---|
| 源文件 | `code/sewpg-bid-frontend/src/utils/permissions.js` |
| 层级 | 前端工具 |
| 领域 | 共享 |
| 行数 | ~70 |

**职责**: 角色权限模型：`T` 技术标专员（仅 tech 工作区）/ `B` 商务标专员（仅 business）/ `TB` 标书统筹（双工作区 + 设置与全局审计写权限）；`canAccessWorkspace/defaultWorkspaceFor/canWriteSettings` 等判定与 hooks。

## 调用链
- **上游**: `WorkspaceAccess.jsx`（路由守卫）、Settings、AppShell。
- **下游**: 无。

## 中间数据与状态
- 角色→工作区映射常量；user.role 来自登录返回。
