# technical_material_store

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_material_store.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 706 |

**职责**: 技术标素材库门面：包装双轨 `material_store` 并强制「技术标/」空间与写入根白名单，接入技术标专属能力——证书台账、标签 Excel 导入（精确+模糊）、机型选项、拆分器复用、索引刷新钩子。

## Input / Output
- Input: 路由层素材请求；写路径必须位于 `技术标/{标准文件|客户定制|项目定制}`（旧名「客户素材/项目素材」自动改写）。
- Output: 过滤后的技术素材/Wiki 数据；证书台账 CRUD/批量/增量/建议（`material_certificate_time`）；标签导入 preview/commit；`turbine_model_options`；结构变更后 `_refresh_index` 重建 JSON 索引。

## 调用链
- **上游**: `routes/technical.py` 素材/证书/Wiki 端点组、`technical_gap_*`、`tech_assembly`、`technical_wiki_generation`。
- **下游**: `material_store`、`material_certificate_time`、`material_tag_import(_fuzzy)`、`technical_material_paths`、`technical_turbine_material_options`、`business_material_splitter`（拆分复用）、`turbine_models`、`scoped_material_urls`、DB `WikiAttachment`。

## 中间数据与状态
- 技术标空间路径约束；`technical_material_index.json` 刷新钩子；证书数据在素材 ext 字段。
