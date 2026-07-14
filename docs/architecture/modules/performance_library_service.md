# performance_library_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/performance_library_service.py` |
| 层级 | 服务层 |
| 领域 | 业绩库 |
| 行数 | 481 |

**职责**: 旧版单条业绩库（PERF- 记录）：记录 CRUD、业绩 Word 上传/下载。docstring 明示当前主模型已是 package/category（`performance_package_service`），本服务仅为历史 API 兼容与迁移读取保留。

## Input / Output
- 记录字段：scope(standard/customer/project)、reviewStatus(draft/reviewed/disabled)、bidType、tags；Word 附件存 MinIO。

## 调用链
- **上游**: `route_performance` 记录端点组、`performance_material_resolver`。
- **下游**: DB（raw SQL 经 async_session）、`material_runtime_tables`、`material_tags`、`minio_client`。

## 中间数据与状态
- 业绩记录表（runtime tables 建）；PERF- id 前缀。
