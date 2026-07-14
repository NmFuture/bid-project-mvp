# material_wiki_tree

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_wiki_tree.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 66 |

**职责**: Wiki 树上下文组装纯函数：按标类可见性过滤根节点，递归收集可见节点集与树结构（WIKI-xxxx id、folder/article 图标）。

## 调用链
- **上游**: `material_wiki_list_operations`。
- **下游**: `material_wiki_scope`（标类可见性）。

## 中间数据与状态
- 无 IO。
