# filename_utils

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/filename_utils.py` |
| 层级 | 服务层 |
| 领域 | 基础设施与通用 |
| 行数 | 63 |

**职责**: 文件名 UTF-8 字节预算裁剪 `short_filename`（默认 128 字节）：防止长中文标题产生超长 MinIO 对象名或意外嵌套 key，保后缀截前段。

## 调用链
- **上游**: `material_cleaning`、`material_wiki_attachment_operations`。
- **下游**: 无。

## 中间数据与状态
- 无。
