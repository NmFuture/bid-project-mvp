# material_wiki_list_operations

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_wiki_list_operations.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 58 |

**职责**: Wiki 列表查询操作：读全量 `wiki_nodes` 组树（标类可见性过滤），选中节点加载其 `wiki_docs` 文档与附件清单，附 tag/适用标类选项。

## Input / Output
- Input: bid_type + node_id（空则默认选中）。
- Output: `{tree, selected(doc+attachments), tagOptions, applicableTypeOptions}`。

## 调用链
- **上游**: `material_store.wiki_list`（`GET /api/{track}/materials/wiki`）。
- **下游**: DB `wiki_nodes/wiki_docs/wiki_attachments`、`material_wiki_tree`、`material_wiki_attachment_operations`、`workspace_artifacts`。

## 中间数据与状态
- 无自有状态。
