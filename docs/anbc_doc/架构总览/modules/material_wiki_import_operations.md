# material_wiki_import_operations

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_wiki_import_operations.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 247 |

**职责**: 生成版 Wiki 蓝图导入执行：按模式（create 新建根 / update / replace 清旧建新 / refresh）把蓝图节点树写入 `wiki_nodes`/`wiki_docs`，附件对象同步清理，平台 Wiki 章节保护。

## Input / Output
- Input: root_title + 节点树 + mode + bid_type。
- Output: 导入结果（节点计数、根 id、消息）；写 DB `WikiNode/WikiDoc/WikiAttachment`。

## 调用链
- **上游**: `material_store.import_generated_wiki_blueprint`（← 两轨 wiki_generation）。
- **下游**: DB 三表、`material_wiki_import`（规约）、`material_wiki_attachment_operations`（对象清理）、`material_taxonomy`（平台章节名）、`material_wiki_scope`。

## 中间数据与状态
- `wiki_nodes`/`wiki_docs` 表；replace 模式的旧树清理。
