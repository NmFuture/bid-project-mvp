# fe_technical_gap_helpers（technicalGapRecognitionHelpers + technicalInterpretation）

| | |
|---|---|
| 源文件 | `workspaces/technical/pages/{technicalGapRecognitionHelpers.js, technicalInterpretation.js}` |
| 层级 | 前端逻辑 |
| 领域 | 技术标 |

**职责**:
- **gapRecognitionHelpers**：缺口页纯函数集——附表任务与 fillTask 关联（blankSource.id 匹配）、AI 填写默认参考素材（人工选择优先，否则按来源矩阵 sourceRouting 的 recommendedMaterials）、默认解析字段、最新产物、候选预览选项、证据片段取值。
- **technicalInterpretation**：招标解读的展示分组（8 个固定组 + 类别别名归并，如 CMS/一次调频/国产化归入同组）、状态标签、表格行构建。

## 调用链
- **上游**: TechnicalGapRecognition、TechnicalTenderReview。
- **下游**: 无（纯函数，有配套 .test.mjs）。
