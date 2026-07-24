# fe_page_material_wiki（Business/TechnicalMaterialWiki）

| | |
|---|---|
| 源文件 | `workspaces/{business,technical}/pages/*MaterialWiki.jsx（284/318）` |
| 层级 | 前端页面 |
| 领域 | 共享 |

**职责**: Wiki 页 `/workspace/{slug}/materials/wiki`：节点树浏览与选中文档展示（MarkdownLite 渲染）、节点 CRUD/移动、附件上传下载、AI 摘要刷新、`bootstrap` 生成/重建 Wiki（技术标为镜像三级目录的确定性重建，商务标为 LLM 精修链路）。

## 调用链
- **下游**: `{track}MaterialsAPI` wiki 端点组。

## 中间数据与状态
- 树选中节点；生成中状态。
