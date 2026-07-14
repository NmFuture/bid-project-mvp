# fe_page_material_db（Business/TechnicalMaterialDB）

| | |
|---|---|
| 源文件 | `workspaces/{business/pages/BusinessMaterialDB.jsx(2613), technical/pages/TechnicalMaterialDB.jsx(3211)}` |
| 层级 | 前端页面 |
| 领域 | 共享 |

**职责**: 素材库页 `/workspace/{slug}/materials/raw`——前端最大的两个文件：目录树 + 文件列表（多维过滤：tier/客户/项目/清洗状态/tag/关键词；商务另有素材类型 businessMaterialKind，技术另有机型），上传（拖拽/目录、tier 与归属选择、冲突策略）、移动/改名/删除、AI 拆分（preview→confirm 交互）、清洗结果预览（OnlyOffice）、打标（技术标含批量打标/批量删除/Excel 标签导入 preview→commit 含模糊匹配确认、证书时间批量识别）。素材预览为页内弹层（规约：不设独立路由）。

## 调用链
- **下游**: `{track}MaterialsAPI`（全部素材端点）、OnlyOffice 组件、FilterBar/Pagination 等共享组件。

## 中间数据与状态
- 树选中路径、过滤器、上传队列、拆分预览片段、标签导入三区（matched/ambiguous/fuzzy）。
