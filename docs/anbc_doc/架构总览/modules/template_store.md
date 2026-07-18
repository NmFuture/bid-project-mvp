# template_store

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/template_store.py` |
| 层级 | 服务层 |
| 领域 | 基础设施与通用 |
| 行数 | 501 |

**职责**: 模板资产库：默认投标模板（双轨，回退模板 `投标文件-模板.docx`）与 Excel 模板表（性能保证/项目业绩）的存取，docx 有效性校验（zip 结构+document.xml+最小 1KB），结构化表登记。

## Input / Output
- `resolve_fallback_bid_template_file_sync(bid_type)`：项目无模板时的回退（缺口计划/项目 template-fallback 用）；`is_valid_docx_file/bytes/stream`。

## 调用链
- **上游**: `bid_project_service`（template-fallback）、`business_gap_planning`、`outline_generation`、`system_settings`、`workspace_project_access`。
- **下游**: DB `TemplateAsset/StructuredTable`、`minio_client`（bid-templates）、`material_runtime_tables`。

## 中间数据与状态
- `template_assets`/`structured_tables` 表；MinIO `bid-templates` 桶。
