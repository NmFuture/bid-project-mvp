# business_material_splitter

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_material_splitter.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 1511 |

**职责**: 素材 AI 拆分引擎（商务/技术共用实现）：把成册 docx 按模板关键词（投标函/授权书/承诺函/价格表等）+ LLM 辅助切成多份独立素材片段，预览→确认两段式落库（schema `bid-business-material-split-plan-v1`）。

## Input（输入）
- `preview_business_material_split(file_id, target_path, ai_mode)`：源文件（MinIO 下载）、aiMode（auto 等）。
- `confirm_business_material_split(file_id, fragments, target_path, on_conflict)`：用户确认的片段清单。

## Output（输出）
- 预览：片段计划（标题/页范围/类别）；确认：按片段切出的 docx 逐个入库（RawFile + MinIO），保留原文件。

## 调用链
- **上游**: `business_material_store`（business-split 端点）、`technical_material_store`（技术标 split 复用同一实现）。
- **下游**: `opencode_client`（LLM 辅助切分）、`minio_client`、DB `RawFile`、`system_settings`、lxml/python-docx（OOXML 级切割）。

## 中间数据与状态
- 拆分计划 schema 常量；`TEMPLATE_KEYWORDS` 模板关键词表；无独立表（结果即新素材文件）。
