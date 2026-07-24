# fe_page_parse_result（Business/TechnicalParseResult）

| | |
|---|---|
| 源文件 | `workspaces/{business,technical}/pages/*ParseResult.jsx（551/553）` |
| 层级 | 前端页面 |
| 领域 | 共享 |

**职责**: 阶段1页 `/projects/:id/template-directory`：解析产物确认与目录生成入口——查看解析字段与资产（附表 blankDocx、商务侧承诺函/商务评分），OnlyOffice 预览/编辑，逐项或一键 approve；触发目录生成（`directory-generation/run`，技术标订阅 SSE `/stream` 进度），完成后进入 outline。

## 调用链
- **下游**: `{track}ParseAPI`（results/appendix preview|approve）、`{track}DirectoryAPI`（run/status/stream）、OnlyOffice 组件、阶段进度组件。

## 中间数据与状态
- 目录生成三步任务进度（准备候选→futurecode 语义审核→保存）；approve 状态。
