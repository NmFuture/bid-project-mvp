# material_wiki_node_operations

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_wiki_node_operations.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 90 |

**职责**: Wiki 节点维护仅剩两项：移动（inside/before/after，path 级联）与 AI 摘要刷新；创建/更新/删除已随 deadcode-03/04 删除，节点树由蓝图导入（`material_wiki_import_operations`）产生。

## Input / Output
- Input: node_id(WIKI-xxxx)/移动目标/刷新请求。
- Output: 操作后最新 wiki_list；非法节点抛 PeripheralError。

## 调用链
- **上游**: `material_store` 的 `wiki_move`/`refresh_summary`。
- **下游**: DB `wiki_nodes/wiki_docs/wiki_attachments`、`material_wiki_scope`（bidTypes 继承）、`material_wiki_attachment_operations`、`wiki_export`。

## 中间数据与状态
- 节点 path 级联维护；sort_order。
