---
name: bid-business-tender-structured-parser
description: 用于 S1 阶段解析商务标招标文件，只抽取项目名称、招标编号、招标人、代理机构、递交截止时间、资格要求、投标人须知前附表、商务废标项、商务评分细则，并输出可追溯结构化 JSON。
---

# 商务标招标文件结构化解析工作流

当后端提供 `s1_parse_manifest.json` 时，先执行：

```bash
s1parse <manifest>
```

该命令生成 `candidate_package.json`、`review_plan.json` 和分页后的 `ai_tasks/<module>/part-NNN.json`，工作流阶段为 `prepared`。随后由当前 opencode agent 通过 Bash 小输出命令查看任务、读取单个 task payload，并写入对应的 `ai_decisions/<module>/part-NNN.json`。

完成 AI 决策后执行：

```bash
s1parse finalize <manifest>
```

最终结构化结果由 `finalize` 写入 `structuredResultPath`，标准输出只打印精简摘要 JSON。

## 解析目标

本 skill 只解析以下信息：

- 项目名称
- 招标编号
- 招标人
- 代理机构
- 递交截止时间
- 资格要求
- 投标人须知前附表
- 商务废标项
- 商务评分细则

## 协作模型

1. 结构层：脚本抽取文本、章节、段落块、表格块、行列位置、引用关系和确定性结构，生成 `candidate_package.json`。项目基础信息、投标人须知前附表和明确商务评分表写入 `deterministicExtracts`。
2. 审查层：AI 只处理少量有证据约束的语义裁判。AI 输入是资格要求候选、商务废标候选或疑难商务评分表候选。
3. 验真层：脚本读取 AI 决策并逐项校验，确认内容能被 evidence 覆盖、来源中文可读、目标模块边界清晰。
4. 合成层：最终 `s1_structured_result.json` 只能由脚本生成。AI 决策只作为语义裁判输入。

## 候选包契约

`candidate_package.json` 至少包含：

- `documents[]`
- `sections[]`
- `blocks[]`
- `tables[]`
- `deterministicExtracts.projectBasics[]`
- `deterministicExtracts.bidderInstructions[]`
- `deterministicExtracts.scoringTables.business[]`
- `candidates.projectFacts[]`
- `candidates.bidderInstructions[]`
- `candidates.qualification[]`
- `candidates.rejection[]`
- `candidates.scoring[]`
- `candidates.scoringTableReview[]`
- `evidenceIndex`

每个候选必须带 `candidateId` 或 `id`、原文内容、章节路径、位置、`evidenceIds` 和可读来源。候选包要给 AI 足够上下文，而不是只给碎片文本。

## AI 任务

AI 审查任务按需生成，通常只会出现：

- `qualification_review`
- `rejection_clause_review`
- `scoring_table_review`

项目基础信息、投标人须知前附表、明确商务评分表由脚本确定性输出，不进入 AI 决策。若文档没有某类语义候选，该类 task 不出现在 `review_plan.json`。

资格任务只判断真正影响投标人资格的条件。

废标任务只判断影响投标有效性的商务废标、否决、无效投标、不予受理、实质性响应风险条款。

疑难评分表任务只判断是否属于商务评分细则及其边界。

`review_plan.json` 至少包含：

- `tasks[].taskId`
- `tasks[].taskPath`
- `tasks[].decisionPath`
- `tasks[].required`
- `taskCount` / `requiredTaskCount`
- `deterministicModules`
- `aiReviewModules`
- `skippedAiModules`

## opencode agent 执行要求

任务编排、单 task 裁判和状态检查由当前 opencode agent 通过 Bash 命令完成：

```bash
s1parse tasks <manifest>
s1parse task <manifest> <taskId>
s1parse decision-all <manifest> <taskId> <accepted|rejected|needsReview> <fieldType> <reason>
s1parse decision-set <manifest> <taskId> <acceptedIdsCsv> <rejectedIdsCsv> <needsReviewIdsCsv> <defaultDecision> <fieldType> <reason>
s1parse qualification-item <manifest> <taskId> <content> <applicableScope> <evidenceIdsCsv> <sourceText> <reason>
s1parse validate-decision <manifest> <taskId>
s1parse status <manifest>
```

生产执行中，商务废标和商务评分任务用 `decision-all` 或 `decision-set` 生成 AI 决策文件。

资格要求任务不得使用 `decision-all` 或 `decision-set` 自动拆分整节切片；必须由当前 AI 基于 `s1parse task` 返回的 `candidates[].lines[]` 逐条判断，并用 `qualification-item` 写入每一条 AI 原始拆分结果。

资格要求通用拆分规则：

- “通用资格条件”“专用资格条件”“业绩要求”“资格能力要求”等副标题、父标题不作为条款。
- “标段一和标段二（需同时满足）”“标段五（需同时满足）”等范围提示行不作为条款，只作为后续条款的 `applicableScope`。
- `3.1.2 投标人财务、信誉等方面应具备下列条件：` 这类父级引导句不作为条款，子项逐条输出。
- 同一实质要求在不同标段下重复出现时，按不同适用范围分别输出，不按内容去重。
- `3.2.3`、`3.2.4`、`3.2.5` 这类项目级资格条款适用范围为本项目或全部标段，不继承上一条“标段五”等范围提示。

禁止用 Bash heredoc、临时 Python 小脚本或手写文件覆盖 `ai_decisions`。必须通过上述 `s1parse` 命令读取任务、写入决策并校验。

禁止用 read 工具打开 `review_plan.json`、`candidate_package.json` 或 `ai_tasks/**` 来绕过任务命令；应使用 `s1parse tasks <manifest>` 和 `s1parse task <manifest> <taskId>` 查看任务。

禁止使用 opencode 的 Task/subagent/子代理/任务委派工具处理 AI 审查；不得调用 Task 工具。所有裁判必须由当前 agent 按当前任务逐项完成。

## AI 决策契约

AI 决策默认写入 `review_plan.json` 指定的 `ai_decisions/<module>/part-NNN.json`。每个文件必须是 JSON 对象：

```json
{
  "schemaVersion": "bid-business-ai-decision-v1",
  "task": "qualification_review",
  "taskId": "qualification_review/part-001",
  "adapter": "opencode-agent",
  "accepted": [],
  "rejected": [],
  "needsReview": [],
  "reason": "",
  "evidenceIds": []
}
```

`accepted[]`、`rejected[]`、`needsReview[]` 的元素必须包含：

```json
{
  "candidateId": "QUALIFICATION-CAND-DOC-1-0001",
  "decision": "accepted",
  "fieldType": "qualification_requirement",
  "content": "候选原文或候选摘要",
  "applicableScope": "全部标段",
  "sourceText": "招标文件 > 投标人资格要求",
  "reason": "语义判断理由",
  "evidenceIds": ["DOC-1:L328"]
}
```

## 最终输出

最终 `s1_structured_result.json` 只保留以下结构化结果：

- `structured.workflow`
- `structured.sourceDocuments[]`
- `structured.fieldGroups.projectBasics[]`
- `structured.fieldGroups.qualificationRequirements[]`
- `structured.fieldGroups.bidderInstructions[]`
- `structured.fieldGroups.commercialRejectionClauses[]`
- `structured.scoringCriteria.business[]`
- `structured.projectFactFields[]`
- `structured.coverage[]`
- `structured.projectDates.endDate`

其中 `projectBasics[]` 只包含 `projectName`、`tenderNo`、`tenderer`、`tenderAgency`、`bidDeadline`。

## 验真规则

- 项目基础信息优先来自投标人须知前附表、封面或招标公告中的明确字段；正文散文不覆盖结构化字段。
- 递交截止时间从招标公告、投标文件递交、开标时间附近检索，并保留来源。
- 投标人须知前附表由脚本拆表，输出条款号、条款名称、编列内容、表格位置和 evidence ID。
- 资格要求输出投标人资格条件。
- 商务废标项输出影响投标有效性的条款。
- 商务评分细则输出商务评分项。
- 所有最终记录保留 `sourceFile`、`sourceDocumentId`、`section`、`evidence`、`evidenceLocation`，并尽量保留 `evidenceIds`。
