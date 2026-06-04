---
name: bid-business-template-extractor
description: 用于从 S1 商务招标 DOCX 的“投标文件格式”或“响应文件格式”正文区域召回候选模板，由当前执行 agent 分批裁决真实模板起点与边界，再由脚本校验、汇总、切片生成后端兼容附件产物。
---

# 商务标模板提取器

本 skill 用在 S1 商务招标文件解析流程中，负责识别并切出商务投标/响应文件格式章节里的附件模板。它不解析评分办法、资格要求、投标人须知、承诺要求或项目核心字段。

整体职责分三层：

- 脚本 prepare：定位格式章节、排除合同/价格/履约保证金等非投标格式章节，高召回召回疑似标题和压缩证据窗口，不切片。
- 当前 opencode agent：基于分批证据做语义裁决，先判断每个疑似标题的角色，再只对 `template_start` 确认最终起止边界。
- 脚本 finalize：校验 agent 裁决，拒绝跨越边界参考标题的范围，汇总为 `llm_boundary_decisions.json`，再切片输出模板 DOCX。

脚本和 `btplbound` 不得调用外部大模型，不得内嵌模板语义裁决；真正的语义判断必须由当前执行 agent 完成。

## 1. 候选准备

运行 prepare：

```bash
python scripts/run_from_manifest.py <manifest>
```

`manifest` 必须包含 `projectId`、`outputDir`、`documents[]`，并设置 `"stage": "prepare"`。prepare 只允许在“投标文件格式”“响应文件格式”“商务投标文件格式”“商务响应文件格式”等正式格式章节中生成候选。

prepare 产物：

- `<documentOutput>/blocks.json`
- `<documentOutput>/regions.json`
- `<documentOutput>/excluded_regions.json`
- `<documentOutput>/candidate_templates.json`
- `<documentOutput>/candidate_windows.json`
- `<outputDir>/business_template_extraction.json`

`candidate_templates.json` 的语义是“待 AI 裁决的高召回疑似标题清单”，不是脚本确认模板清单。脚本应尽量别漏：标题样式、目录级别、加粗、居中、分页起始、靠左短标题、序号、附件号、后接表格等都可以成为候选信号。`合同附件格式`、`合同价格组成`、`履约保证金格式`、`合同条款及格式` 等非投标/响应文件格式章节只能进入排除记录，不得进入候选、裁决或最终结果。prepare 阶段不得生成 `boundaries.json` 或 `templates/*.docx`。

## 2. Agent 分批裁决

后端会要求 agent 使用容器命令 `btplbound` 分批执行。该命令只是 skill 脚本包装器，负责取证、校验、保存进度和汇总。

标准流程：

```bash
btplbound status <manifest>
btplbound candidate-batch <manifest> next
btplbound candidate-decision <manifest> <批号> <候选裁决文件>
btplbound boundary-batch <manifest> next
btplbound boundary-decision <manifest> <批号> <边界裁决文件>
btplbound finalize <manifest>
```

候选裁决先按每批 8 个候选判断标题角色。候选批全部完成后，再只对已确认的 `template_start` 分批确认边界。这样第二轮能看到所有边界参考，避免只看下一个输出模板而吞并中间的父级章节或边界标题。

候选裁决文件格式：

```json
{
  "decisions": [
    {
      "candidateId": "CAND-0001",
      "isTemplateStart": true,
      "headingRole": "template_start",
      "rejectReason": "",
      "templateTitle": "投标函",
      "templateType": "bid_letter",
      "confidence": 0.92,
      "reason": "标题后有正文、填写字段或签章栏。",
      "needsReview": false
    }
  ]
}
```

`headingRole` 必须取以下四类之一：

- `template_start`：正式模板起点，进入 `boundary-batch`，并作为边界参考。
- `section_container`：父级章节标题，不输出模板，但作为边界参考阻断前一个模板。
- `boundary_only`：只作为新内容段边界，不输出模板，但作为边界参考阻断前一个模板。
- `reject`：目录项、正文、噪声或无效标题，不输出模板，也不作为边界参考。

旧格式只返回 `isTemplateStart` 时仍兼容：`true` 自动视为 `template_start`，`false` 自动视为 `reject`。

边界裁决文件格式：

```json
{
  "decisions": [
    {
      "candidateId": "CAND-0001",
      "startBlockId": 10,
      "endBlockId": 25,
      "confidence": 0.92,
      "reason": "遇到下一个真实模板标题前截断。",
      "needsReview": false
    }
  ]
}
```

裁决规则：

- 目录项、目录列表、封面字段不得作为正式模板。
- 标题后没有正文、表格、填写字段或签章栏时拒绝。
- 当前模板必须在下一个边界参考标题前结束；边界参考包括 `template_start`、`section_container`、`boundary_only`。
- 容器标题不能吞并多个子模板；父级章节应标为 `section_container`，多个独立子模板要分别裁决。
- 表格型模板可以短正文成立，但标题后必须紧跟真实表格或可填写表格。
- `startBlockId`、`endBlockId` 必须在格式章节内，不得跨入合同附件、合同价格组成、履约保证金格式等排除章节。
- `confidence < 0.75` 或 `needsReview: true` 只能进入 `review.md`，不得生成正式模板 DOCX。

## 3. 汇总与切片

`btplbound finalize <manifest>` 会在每个文档输出目录生成兼容后续 finalize 的：

```text
<documentOutput>/llm_boundary_decisions.json
```

该文件固定包含：

```json
{
  "schemaVersion": "bid-business-template-extractor-boundary-decisions-v1",
  "decider": "executing_agent",
  "decisions": []
}
```

写完该文件后，后端再运行：

```bash
python scripts/run_from_manifest.py <manifest>
```

`manifest` 设置 `"stage": "finalize"`。finalize 默认必须读取 agent 裁决；缺少 `llm_boundary_decisions.json` 时不得切片，只能在 `business_template_extraction.json.warnings` 记录缺少裁决。

只有显式设置 `"fallbackMode": "script"` 时，才允许使用脚本规则边界作为诊断或紧急回退，并必须记录 `quality.scriptFallbackUsed: true`。常规解析路径不得依赖脚本兜底。

验证层必须拒绝：

- 越出格式章节的边界。
- 重叠边界。
- `endBlockId <= startBlockId`。
- 目录污染、目录项污染。
- 低置信度或 `needsReview` 的正式输出。
- 跨越下一个边界参考标题的 `endBlockId`。

最终只对 validated templates 执行 DOCX 切片。`business_template_extraction.json` 保持后端兼容字段，并维护：

- `rejectedCandidates`
- `warnings`
- `quality.catalogRejectedCount`
- `quality.outsideFormatRegionRejectedCount`
- `quality.lowConfidenceCount`
- `quality.needsReviewCount`
- `quality.agentDecisionCount`
- `quality.agentRejectedCount`
- `quality.headingDecisionCount`
- `quality.acceptedTemplateCount`
- `quality.boundaryReferenceCount`
- `quality.sectionContainerCount`
- `quality.boundaryOnlyCount`
- `quality.rejectedCount`
- `quality.scriptFallbackUsed`

## 4. 验收要点

必须检查：

- 无 `llm_boundary_decisions.json` 时默认不生成 appendices，并提示缺少 agent 裁决。
- mock agent decisions 后，最终边界使用 agent 决策，不使用脚本规则裁决。
- `btplbound status`、`candidate-batch`、`candidate-decision`、`boundary-batch`、`boundary-decision` 不应触发后端早停。
- 只有 `btplbound finalize <manifest>` 输出终态 JSON 时，后端才提前结束等待并读取脚本产物。
- 目录项 reject 后不进入结果。
- 合同附件章节不进入候选、裁决或结果。
- 低置信度模板进入 `review.md`，不切片。
- 投标函尾部保留，表格型模板成立，多个模板不粘连。

参考验收样例：

- 输入招标文件：`C:\Users\99065\Documents\商务标V2\解析增强\（闻喜、太谷、寿阳、武乡）480MW风力发电机组(含钢塔筒、锚栓)及附属设备采购(采购文件).docx`
- 期望：能看到 agent 裁决数量大于 0，`scriptFallbackUsed` 为 `false`，最终模板数量和标题集合与既有参考结果大体一致，且不得混入合同附件或目录项。
