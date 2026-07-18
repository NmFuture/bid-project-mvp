# material_raw_file_filter

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_raw_file_filter.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 204 |

**职责**: 素材文件多维过滤与分页 payload 组装：标类/项目/客户/档位/清洗状态/素材类型/tag/标题/关键词逐条判定，并汇集当前范围内的 tag 选项供前端筛选器。

## Input / Output
- Input: ORM 行列表 + 全部过滤参数。
- Output: `build_raw_files_payload` → 分页 payload + tagOptions；`raw_file_matches_bid_type` / `raw_folder_matches_bid_type`（归属判定，被更新/移动/访问操作复用）。

## 调用链
- **上游**: `material_raw_file_operations`、`material_raw_update/move/access/lifecycle_operations`、`material_certificate_time`。
- **下游**: `identity`（客户/项目匹配）、`material_tags`、`material_taxonomy`、`material_folder_scope`、`material_wiki_scope`。

## 中间数据与状态
- 无 IO；过滤语义集中于此（内存过滤，非 SQL）。
