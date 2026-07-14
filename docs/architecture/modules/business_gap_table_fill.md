# business_gap_table_fill

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_gap_table_fill.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 145 |

**职责**: 商务标表格填写的输入准备：解析请求里的源素材引用（多种字段形态归一去重、补全 businessMaterialKind 标签），从 MinIO 下载源素材与目标模板到本地供填表 Skill 使用。

## Input（输入）
- `business_table_fill_source_materials(project, data)`：请求 `sourceMaterials|materials|materialIds`（字符串或对象混合），对照素材选择器索引（`build_business_gap_material_picker_index`）补全。
- `prepare_business_table_fill_sources/target`：素材/模板 → 本地文件。

## Output（输出）
- 规范化源素材清单（id/materialName/businessMaterialKind）；本地化的源文件与目标模板路径。

## 调用链
- **上游**: `business_gap_service.table_fill`。
- **下游**: `business_gap_planning`（素材索引）、`business_material_store`、`minio_client`、`file_utils`。

## 中间数据与状态
- workspace 本地临时文件；不落新表。
