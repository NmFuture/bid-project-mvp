# material_wiki_import

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_wiki_import.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 76 |

**职责**: 生成版 Wiki 蓝图导入的纯函数规约：导入模式归一（create/update/replace/refresh）、根节点规格构建（标题安全化+标类推断）、节点标题/markdown/tags/bidTypes 提取。

## 调用链
- **上游**: `material_wiki_import_operations`。
- **下游**: `material_wiki_scope`、`workspace_artifacts`。

## 中间数据与状态
- 常量：`VALID_WIKI_IMPORT_MODES`、自动节点摘要文案。
