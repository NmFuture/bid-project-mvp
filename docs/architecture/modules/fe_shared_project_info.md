# fe_shared_project_info（projectInfoForm + projectInfoOptions + businessRiskLevel）

| | |
|---|---|
| 源文件 | `code/sewpg-bid-frontend/src/workspaces/{shared/projectInfoForm.js, shared/projectInfoOptions.js, business/businessRiskLevel.js}` |
| 层级 | 前端逻辑 |
| 领域 | 共享 |
| 行数 | ~120 合计 |

**职责**: 「完善项目信息」表单的领域逻辑：机型明细行模型（model/turbineCount/foundationType/source）归一与清洗（兼容 legacy 单机型字段）；选项加载（双轨 `project-info/options` 接口，当前静态回源）；商务风险等级标签映射（high/medium/low→高/中/低风险）。

## 调用链
- **上游**: 两轨 ProjectWizardModal（项目信息弹窗）、TenderReview。
- **下游**: `fe_api`（projectInfoOptionsAPI 两组）。
