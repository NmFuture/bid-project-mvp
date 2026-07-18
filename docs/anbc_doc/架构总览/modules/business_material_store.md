# business_material_store

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_material_store.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 383 |

**职责**: 商务标素材库门面：包装双轨共用 `material_store`，强制路径必须位于「商务标/」空间（越界抛 `BUSINESS_MATERIAL_PATH_REQUIRED`）、payload 注入 bidType、目录树过滤到商务标根；并接入商务拆分器。

## Input / Output
- Input: 路由层素材请求（上传/树/文件/移动/Wiki 等）。
- Output: 过滤后的商务标素材/Wiki 数据；素材 URL 经 `scoped_material_urls.rewrite_material_urls` 重写；AI 拆分 `preview/confirm_business_material_split`。

## 调用链
- **上游**: `routes/business.py` 素材/Wiki 端点组、`business_gap_service/planning/table_fill`、`business_parse_assets`、`business_assembly`、`business_wiki_generation`、`project_fact_materials`。
- **下游**: `material_store`（真正实现）、`business_material_splitter`、`scoped_material_urls`、DB `WikiAttachment`、`peripheral`。

## 中间数据与状态
- 无自有表；商务标空间约束（路径前缀「商务标/」）是双轨隔离在素材层的落点。
