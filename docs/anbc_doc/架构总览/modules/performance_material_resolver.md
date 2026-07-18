# performance_material_resolver

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/performance_material_resolver.py` |
| 层级 | 服务层 |
| 领域 | 业绩库 |
| 行数 | 81 |

**职责**: 业绩素材识别与下载解析：按 id 前缀（PERF-/PERCAT-/PERITEM-）或 sourceType 判定素材是否来自业绩库，并路由到对应服务取下载 payload——缺口填写引用业绩件的桥梁。

## 调用链
- **上游**: `business_gap_service`、`project_fact_materials`。
- **下游**: `performance_library_service`、`performance_package_service`。

## 中间数据与状态
- 来源类型常量（performance_library / performance_package 及下载 source kinds）。
