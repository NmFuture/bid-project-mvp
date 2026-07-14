# fe_page_tender_review（Business/TechnicalTenderReview）

| | |
|---|---|
| 源文件 | `code/sewpg-bid-frontend/src/workspaces/{business/pages/BusinessTenderReview.jsx(1906), technical/pages/TechnicalTenderReview.jsx(1417)}` |
| 层级 | 前端页面 |
| 领域 | 共享 |

**职责**: 解析入口页 `/parse/{track}`：上传招标/模板文件（≤5 个/500MB，pdf/docx/xlsx/图片/zip）→ `upload-and-run` → 进度轮询（超时恢复见 fe_parse_upload_recovery）→ 解析结果展示（项目字段、技术标另有「招标解读」分组表 technicalInterpretation）→ **参与投标决策**（participate 后弹 ProjectWizardModal 完善项目信息并转正式项目）。不暴露「先建项目」（后台静默建临时承载）。

## Input / Output
- Input: 上传文件、URL `?projectId=`（恢复既有解析）。
- Output: 解析结果确认与参与决策；跳转项目 template-directory。

## 调用链
- **上游**: 路由 `/parse/business|technical`。
- **下游**: `{track}ParseAPI`（upload-and-run/progress/results）、`{track}ProjectsAPI`（reviewDecision）、OnlyOffice 组件（附表预览）、`fe_project_routes`、`fe_parse_upload_recovery`、ProjectWizardModal。

## 中间数据与状态
- 解析进度轮询；reviewItems 列表；技术标解读分组常量（8 组，别名归并）。
