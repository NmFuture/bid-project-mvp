# fe_page_project_list（Business/TechnicalProjectList + EntryRedirect + WizardModal）

| | |
|---|---|
| 源文件 | `workspaces/{business,technical}/pages/{*ProjectList.jsx(~340), *ProjectEntryRedirect.jsx(~70), *ProjectWizardModal.jsx(471/760)}` |
| 层级 | 前端页面 |
| 领域 | 共享 |

**职责**:
- **ProjectList** `/workspace/{slug}/projects`：项目卡片列表（status/dateRange 过滤分页，只显示 `reviewDecision=participate`），点击按当前阶段路由跳转（`fe_stage_flows`），菜单可回解析页。
- **ProjectEntryRedirect** `/projects/:id`：读项目当前阶段 → 重定向到对应阶段路由。
- **ProjectWizardModal**：完善项目信息弹窗——客户下拉、风机机型明细行（机型+台数+基础形式，`fe_shared_project_info`）、日期等；技术标版本更长（760 行，多机型选型细节）。保存 `PUT /projects/{id}`。

## 调用链
- **下游**: `{track}ProjectsAPI`、`{track}StagesAPI`、`projectInfoOptionsAPI`、`fe_stage_flows`。

## 中间数据与状态
- 列表过滤参数；向导表单态（机型行数组）。
