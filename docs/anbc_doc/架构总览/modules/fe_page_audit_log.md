# fe_page_audit_log（Business/TechnicalAuditLog）

| | |
|---|---|
| 源文件 | `workspaces/{business,technical}/pages/*AuditLog.jsx（369/389）` |
| 层级 | 前端页面 |
| 领域 | 共享 |

**职责**: 审计页 `/workspace/{slug}/logs`：按时间/类型/操作人过滤的审计列表、导出、详情弹窗（AuditDetailModal 展示 diff）。数据已被后端按 bidType 隔离。

## 调用链
- **下游**: `{track}AuditAPI`（list/export/detail）。
