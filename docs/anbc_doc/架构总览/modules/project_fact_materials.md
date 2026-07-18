# project_fact_materials

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/project_fact_materials.py` |
| 层级 | 服务层 |
| 领域 | 基础设施与通用 |
| 行数 | 84 |

**职责**: 项目事实素材的下载准备：按标类路由到对应素材门面，业绩素材走 resolver；优先取清洗版（cleaned），失败回退原始件，本地化供事实表抽取。

## 调用链
- **上游**: `technical_gap_fact_table.prepare_project_fact_material_files`。
- **下游**: `business/technical_material_store`、`performance_material_resolver`、`minio_client`、`bid_project_service`。

## 中间数据与状态
- 本地临时文件；cleaned→raw 回退策略。
