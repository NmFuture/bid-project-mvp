# fe_page_cocreation_editor（Business/TechnicalCoCreationEditor）

| | |
|---|---|
| 源文件 | `workspaces/{business/pages/BusinessCoCreationEditor.jsx(719), technical/pages/TechnicalCoCreationEditor.jsx(502)}` |
| 层级 | 前端页面 |
| 领域 | 共享 |

**职责**: 阶段5/6页 `/projects/:id/editor`：正文生成状态（fill_state 轮询：三步任务/事件/LLM 轨迹 brandFutureCode 展示）+ OnlyOffice 在线共创（documentKey 驱动会话）+ 格式化预设 + 终稿导出（Word/PDF）。商务侧另有 AI 对话（business-chat）与选段重写（suggest→apply 受控替换）；技术侧另有覆盖率查看与导出前检查（export/check）。

## 调用链
- **下游**: `{track}GenerateAPI`（status/run）、`{track}DocumentAPI`（document/save/callback/format/final/pdf）、技术侧 coverage/export、OnlyOfficeWorkspace 组件。

## 中间数据与状态
- fill_state 轮询；编辑器会话；导出检查结果。
