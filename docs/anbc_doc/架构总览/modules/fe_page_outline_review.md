# fe_page_outline_review（Business/TechnicalOutlineReview）

| | |
|---|---|
| 源文件 | `workspaces/{business,technical}/pages/*OutlineReview.jsx（801/794）` |
| 层级 | 前端页面 |
| 领域 | 共享 |

**职责**: 阶段2页 `/projects/:id/outline`：目录树编辑（增删改节点、编号显示 `fe_utils_misc`）、对照招标原文（outline/tender-files OnlyOffice 预览）、规则证据查看；`PUT outline` 保存、技术标可 `regenerate`，`POST outline/confirm` 确认后进入缺口阶段（后端联动推阶段）。

## 调用链
- **下游**: `{track}OutlineAPI`（get/save/confirm/regenerate）、`{track}DirectoryAPI`、OnlyOffice 组件。

## 中间数据与状态
- 目录树本地编辑态；reviewStatus draft→confirmed。
