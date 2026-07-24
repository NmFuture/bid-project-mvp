# audit_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/audit_service.py` |
| 层级 | 服务层 |
| 领域 | 权限与审计 |
| 行数 | 145 |

**职责**: 全局审计服务：记录操作日志（action/action_type/module/target/status/user/diff/IP/UA）到 `audit_logs` 表，查询/导出/详情，两轨审计门面在其上加 bidType 过滤。

## Input / Output
- `record(...)`：登录、OCR、生成等关键动作的审计写入（无用户时记「系统」）。
- `list/export/detail(filters)`：分页查询（bidType 过滤经 metadata）。

## 调用链
- **上游**: `route_auth`、`business/technical_audit_service`、`ocr_service`、`bid_generation_flow`、`system_settings`。
- **下游**: DB `AuditLog`（audit_logs 表）、`material_runtime_tables`、`peripheral`。

## 中间数据与状态
- `audit_logs` 表；metadata 内 bidType 用于双轨隔离。
