# material_wiki_node_operations

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_wiki_node_operations.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 203 |

**职责**: Wiki 节点 CRUD 操作：创建（path 级联、bidTypes 继承）、更新（标题/内容/tags/适用标类）、删除（级联子树+附件对象清理）、移动（inside/before/after）、AI 摘要刷新。

## Input / Output
- Input: node_id(WIKI-xxxx)/parent_id/title/is_folder/更新体/移动目标。
- Output: 操作后最新 wiki_list；非法节点抛 PeripheralError。

## 调用链
- **上游**: `material_store` 的 wiki_create/update/delete/move/refresh_summary。
- **下游**: DB `wiki_nodes/wiki_docs/wiki_attachments`、`material_wiki_scope`（bidTypes 继承）、`material_wiki_attachment_operations`（对象清理）、`wiki_export`。

## 中间数据与状态
- 节点 path 级联维护；sort_order。
