# wiki_export

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/wiki_export.py` |
| 层级 | 服务层 |
| 领域 | Wiki通用 |
| 行数 | 311 |

**职责**: Wiki 导出器：经内部 API（默认 `http://fastapi:8000`）拉取 Wiki 树与节点内容，导出为 markdown 文件组（index/skeleton/rules/synonyms + 卡片目录），供正文装配 Skill 作为知识输入。

## Input / Output
- `export_wiki(bid_type, output_dir, ...)`：urllib 请求内部 API → 落盘 md 文件组；身份字段集（material_id/customer/project 等）随卡片导出。

## 调用链
- **上游**: `tech_assembly`（装配前导出 Wiki）、`material_wiki_node_operations`。
- **下游**: 内部 HTTP API（自举调用 fastapi）、文件系统。

## 中间数据与状态
- 装配工作目录内的 wiki md 文件组；`WIKI_FILES` 固定文件名。
