# material_cleaning

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_cleaning.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 298 |

**职责**: 素材格式清洗执行器（worker 侧 `material_cleaning` 任务）：把 pdf/xls(x/m)/docx 清洗为规范 docx（Skill `bid-material-format-cleaner` subprocess），产物回存 MinIO 并更新 cleanStatus。

## Input / Output
- Input: `clean_material_file_sync(raw_id, data)`（RAW-xxxx）；可清洗后缀 `CLEANABLE_SUFFIXES={.pdf,.xlsx,.xls,.xlsm,.docx}`；长文件名走 `filename_utils.short_filename` 短路径。
- Output: cleaned docx（MinIO，key 记入 ext `cleanedMinioKey/Bucket`）；`cleanStatus: pending→cleaned/failed` + `cleanMessage`。

## 调用链
- **上游**: `redis_worker`（job 分发）、`material_raw_object_operations.enqueue_cleaning_job`（上传后入队）。
- **下游**: Skill `bid-material-format-cleaner`（subprocess）、`minio_client`、DB `raw_files`、`filename_utils`。

## 中间数据与状态
- 临时清洗工作目录；ext_fields 清洗字段；`cleanStatus` 四态之三在此产生（original_only 为不可清洗类型）。
