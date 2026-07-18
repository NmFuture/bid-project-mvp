# material_tags

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_tags.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 51 |

**职责**: 素材标签归一化的唯一规则：任意形态（字符串/JSON/嵌套列表）→ 去空白、截断 40 字、casefold 去重、上限 20 个。

## 调用链
- **上游**: 路由上传、`material_update/upload_metadata`、`material_tag_import(_fuzzy)`、`technical_material_index`、`performance_*`、`business_wiki_generation`。
- **下游**: 无。

## 中间数据与状态
- 常量 `MAX_MATERIAL_TAGS=20`、`MAX_MATERIAL_TAG_LENGTH=40`。
