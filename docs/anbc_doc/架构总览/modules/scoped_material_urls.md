# scoped_material_urls

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/scoped_material_urls.py` |
| 层级 | 服务层 |
| 领域 | 基础设施与通用 |
| 行数 | 22 |

**职责**: 素材内部 URL 占位符机制：服务层产出 `__scoped_material_raw__`/`__scoped_material_wiki__` 前缀的中性地址，出口处按轨改写为真实 API 前缀（`rewrite_material_urls` 递归替换）——同一份素材实现服务双轨 URL。

## 调用链
- **上游**: `material_store`、`business/technical_material_store`（出口改写）、`material_raw_access/upload_target`、`wiki_export`。
- **下游**: 无。

## 中间数据与状态
- 两个前缀常量。
