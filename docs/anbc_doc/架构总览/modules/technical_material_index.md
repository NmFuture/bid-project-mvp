# technical_material_index

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_material_index.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 大型 |

**职责**: 技术标素材三级目录 JSON 索引的构建与维护——整套素材下游（解析候选/Wiki/标签/召回）的「地基」模块。schemaVersion=2 起 **tag 真值在本 JSON**（DB ext_fields.tags 退役为迁移种子）。

## Input（输入）
- 结构从 DB 实时读（raw_folders/raw_files）；tag 从旧 JSON 按认领键贴回（文件 `RAW-id`、目录 `folderId`）；AI 预览从 DB 缓存（`ext_fields.techWikiPreview`）按内容指纹注入。
- `set_tags_for_node(target_id, tags)`：人工打标（RAW- 前缀=文件，否则 folderId/路径）。

## Output（输出）
- `technical_material_index.json`（`documents卷/_runtime/materials/`）：tiers(standard/customer/project) → folders(第3级) → files（含 cleanStatus、tags、preview）；深层文件归并到 3 级祖先、path 保留完整路径。
- 只读接口兜底：`GET /api/technical/materials/index` 空则即时重建。

## 调用链
- **上游**: `technical_material_store._refresh_index`（所有结构变更钩子）、`routes/technical.py` index 端点、Wiki/解析候选/缺口召回等下游。
- **下游**: `bid_runtime_state`（原子读写 JSON）、`material_tags`/`material_taxonomy`（归一化）、DB（结构真值）。

## 中间数据与状态
- `_INDEX_WRITE_LOCK`（asyncio 锁：rebuild 与人工打 tag 串行，JSON 为真值写丢即真丢）；`preview_mode` 三态 none/cached/generate；`TAGS_SOURCE_OF_TRUTH="index"`。
