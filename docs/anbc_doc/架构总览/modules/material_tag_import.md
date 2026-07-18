# material_tag_import

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_tag_import.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 357 |

**职责**: 标签 Excel 批量导入的确定性内核：解析清单（文件名称 + 属性1/2/3 列，表头关键词识别）、忽略扩展名匹配素材、同名文件用目录层级列消歧、无法唯一定位归 `ambiguous` 交人工；全角→半角归一抹平「语义同名」差异；tag 追加去重写入。

## Input / Output
- Input: Excel bytes + 目标目录范围；占位文本行（待填写/暂无/无 等）跳过。
- Output: `parse_tag_excel` / `build_preview`：`{matched, ambiguous, unmatched}` 三区预览；commit 阶段按预览项写 `ext_fields.tags`（merge/overwrite 两模式）。

## 调用链
- **上游**: `technical_material_store.raw_tag_import_preview/commit`。
- **下游**: `material_tags`、`minio_client`（commit 时）、openpyxl。

## 中间数据与状态
- 纯函数设计便于单测；全角映射表常量。
