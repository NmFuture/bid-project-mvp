# performance_package_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/performance_package_service.py` |
| 层级 | 服务层 |
| 领域 | 业绩库 |
| 行数 | 2224 |

**职责**: 业绩库主模型（分类/条目/附件）：Excel 汇总表预览与导入建类、分类多维检索（场景/功率/机型/合同/投运年份）、合同附件管理（成册与条目级）、合同 docx 规范化输出（统一宋体/Times 字体、格式版本 15）。

## Input（输入）
- 汇总表 xlsx（preview→import 两段）；分类字段：scope(standard/customer/project)、reviewStatus(draft/reviewed/disabled)、status(enabled/disabled)、tags。
- 附件类型：`summary_table` / `contract_bundle` / `contract_item`。

## Output（输出）
- 分类与条目记录（PERCAT-/PERITEM- id）；附件 MinIO 对象与 OnlyOffice 预览；条目合同 docx 重排产物（OOXML 级处理，内容指纹缓存）。

## 调用链
- **上游**: `route_performance` 分类端点组、`business_gap_planning`（缺口计划的业绩输入）、`performance_material_resolver`。
- **下游**: DB（raw SQL）、`material_runtime_tables`、`minio_client`、`material_tags`、`workspace_project_access`、python-docx/ElementTree。

## 中间数据与状态
- 业绩分类/条目/附件表；`ITEM_CONTRACT_FORMAT_VERSION=15`（重排版本，变更触发重生成）。
