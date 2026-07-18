# fe_parse_upload_recovery（business/technicalParseUploadRecovery.js）

| | |
|---|---|
| 源文件 | `code/sewpg-bid-frontend/src/workspaces/{business,technical}/*ParseUploadRecovery.js` |
| 层级 | 前端逻辑 |
| 领域 | 共享 |
| 行数 | ~100 ×2 |

**职责**: 解析上传的进度轮询与超时恢复：`shouldPollParseProgress`（uploading/running/queued 继续轮）、`pollParseProgressOnce`（progress→完成时取 results）、`isUploadAndRunTimeout`（前端 12s 超时后转入轮询恢复而不是报错——上传解析实际耗时远超请求超时）。

## Input / Output
- Input: projectId + parseClient（对应轨的 parseAPI）。
- Output: `{completed, failed, progress, result}` 轮询结论。

## 调用链
- **上游**: 两轨 TenderReview 解析页。
- **下游**: `fe_api` 的 parse 组（progress/results）。

## 中间数据与状态
- 轮询终态判定：status completed / percentage≥100 / failed|error。
