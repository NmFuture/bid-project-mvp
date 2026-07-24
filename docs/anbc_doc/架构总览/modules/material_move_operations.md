# material_move_operations

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_move_operations.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 231 |

**职责**: 素材移动操作：单文件移动（跨目录换 MinIO key、冲突策略、tier/归属元数据重推导）与整目录移动（保护根不可动、禁止移入自身子孙、批量迁移文件与子目录路径）。

## Input / Output
- Input: file_id/source_path + target(parent)_path + bid_type + on_conflict。
- Output: 移动结果 + 最新树；保护路径与非法目标抛 PeripheralError。

## 调用链
- **上游**: `material_store.raw_move_file/raw_move_folder`。
- **下游**: DB `raw_files/raw_folders`、`material_move_metadata`（ext 重建，含移动审计字段）、`material_folder_scope`（保护/子孙判定）、`material_raw_file_filter`、`minio_client`、`workspace_project_access`。

## 中间数据与状态
- ext 移动记录（sourceMinioKey/lastAction=move）；MinIO 对象复制+删除。
