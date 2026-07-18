# material_wiki_scope

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_wiki_scope.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 62 |

**职责**: Wiki 双轨范围规则：标类归一、节点 bidTypes 继承（父有则承父，否则按当前轨，缺省「通用」）、根标题→标类推断（「商务标…」开头归商务，否则技术）、生成版 Wiki 固定子节点标题清单。

## 调用链
- **上游**: `material_wiki_tree/import(_operations)/attachment/list/node_operations`、`material_raw_file_filter`、`bid_document_flow`。
- **下游**: `bid_type`。

## 中间数据与状态
- 常量：`GENERATED_WIKI_CHILD_TITLES`（01-素材总表…05-使用规则）、`WIKI_TAG_OPTIONS`、平台根标题。
