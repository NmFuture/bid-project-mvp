# fe_utils_workspace

| | |
|---|---|
| 源文件 | `code/sewpg-bid-frontend/src/utils/workspace.js` |
| 层级 | 前端工具 |
| 领域 | 共享 |
| 行数 | ~120 |

**职责**: 双工作区路由与标类映射的唯一定义：`WORKSPACE_TYPES`（tech↔技术标 / business↔商务标）、slug↔bidType 互转、`workspaceRoute/projectRoute` 路由构造、`parseRouteFromBidType`（解析页入口）、hooks（useWorkspaceSlug 等）。

## 调用链
- **上游**: 全部页面、stage flow、App。
- **下游**: react-router。

## 中间数据与状态
- 常量映射；与后端 `bid_type.py` 语义对齐（前后端各一份标类归一）。
