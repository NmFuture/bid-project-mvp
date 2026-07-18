# model_materials

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/models/materials.py` |
| 层级 | 数据模型 |
| 领域 | 素材库 |
| 行数 | ~200 |

**职责**: 素材库 SQLAlchemy ORM 模型：目录树与文件的结构真值。

## 表结构
| 表 | 关键列 |
|---|---|
| `raw_folders` | id、parent_id（自引用级联删）、name、path、`tier`（档位）、bid_type、customer_name、project_id、sort_order |
| `raw_files` | id、folder_id（级联删）、name、size_bytes、mime_type、`minio_key`/`minio_bucket`（默认 bid-materials）、version、**`ext_fields JSONB`**、created/updated_by |
| `raw_folder_deletions` | path 主键（目录删除墓碑记录） |
| `raw_file_versions` | 文件版本历史（与 RawFile 级联） |

## Input / Output
- `to_dict()` 输出前端 camelCase 结构；文件 id 序列化为 `RAW-%04d`；`ext_fields` 承载业务扩展：bidType、项目/客户归属、materialTier、businessMaterialKind、tags、cleanStatus、techWikiPreview（AI 预览缓存）、证书时间等。

## 调用链
- **上游**: `material_*` 服务群（经 `material_runtime_tables`/`store` 访问）。
- **下游**: PostgreSQL。

## 中间数据与状态
- 结构真值在此二表；MinIO 只存字节；JSON 索引是其快照。
