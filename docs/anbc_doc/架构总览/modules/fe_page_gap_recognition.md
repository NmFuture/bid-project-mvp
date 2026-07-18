# fe_page_gap_recognition（Business/TechnicalGapRecognition）

| | |
|---|---|
| 源文件 | `workspaces/{business/pages/BusinessGapRecognition.jsx(2277), technical/pages/TechnicalGapRecognition.jsx(1674)+helpers(js)}` |
| 层级 | 前端页面 |
| 领域 | 共享 |

**职责**: 阶段3/4页 `/projects/:id/gaps`——全站交互最重的页面：缺口检测运行与列表（decision 四/五态分桶统计）、任务详情面板（候选素材卡片选择、素材预览、证据片段）、处理动作（选素材/选模板[商务]/AI 草拟[商务]/AI 填写单条与全部/表格填写/人工上传）、项目事实表编辑（build/save）、提交评审[技术]；完成后触发正文生成 `fill-generation/run` 进入 editor。

- **商务**：`taskActionMode` 按已落地产物（resolvedArtifacts/handlingMode）打标签，候选≠决策。
- **技术**：`technicalActionMode` 按 decision 映射（fill_required+fillTasks→AI填写；review_required→素材匹配；material_required→人工补料）；helpers 提供来源矩阵路由的推荐素材默认值、附表任务关联等。

## 调用链
- **下游**: `{track}GapsAPI`（全部缺口端点）、`{track}MaterialsAPI`（selectable/预览）、`{track}GenerateAPI`、`{track}StagesAPI`、OnlyOfficeEmbed（产物预览）、MaterialMatchProgressModal。

## 中间数据与状态
- 缺口列表与选中项、AI 填写进行中状态（已知问题：质量警示 helper 曾为死代码，见 20260708 复盘 §四.3）。
