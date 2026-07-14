# material_taxonomy

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_taxonomy.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 556 |

**职责**: 素材分类学的常量与推导中心：档位（standard/customer/project 及中文标签）、商务素材类型（fixed 固定素材/ai_fill AI填写/other）、商务类别与子类推导、双轨档位目录规格、保护目录判定、可清洗后缀、平台 Wiki 章节名。

## Input / Output
- `normalize_material_tier/business_material_kind`；`infer_business_material_category/subcategory`（按路径/名称推导）；`clean_status_for_new_file`（可清洗→pending，图片→original_only）；`is_raw_material_protected_folder_path`；`canonical_technical_material_path`。

## 调用链
- **上游**: `material_folder_scope/maintenance`、`material_upload/update/move_metadata`、`material_raw_lifecycle`、`technical_material_index`、`parsing`、`tech_assembly`、`business_wiki_generation`。
- **下游**: `bid_type`。

## 中间数据与状态
- 常量：`TECHNICAL_TIER_FOLDERS`（标准文件/客户定制/项目定制）、`BUSINESS_TIER_FOLDERS`、类别标签与排序、`MATERIAL_LIBRARY_ALLOWED_SUFFIXES`。
