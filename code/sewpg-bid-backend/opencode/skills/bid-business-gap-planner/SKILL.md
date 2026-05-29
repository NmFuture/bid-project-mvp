---
name: bid-business-gap-planner
description: 当用户要求进行商务标 S3 缺口处理、商务响应件缺口识别、business_gap_plan 生成、商务标素材/解析/目录/Wiki 联合判断时使用。以商务目录为主视图，以商务响应件任务为执行单元，输出 business_gap_plan.v1。
---

# Business Bid Gap Planner

## Project Integration Contract

在 `bid-project-mvp` 中，本 skill 的命令入口是：

```bash
businessgap <manifest>
```

也支持本地 runner 形式：

```bash
python scripts/run_from_manifest.py --manifest <manifest> --response summary
```

输入 manifest 由后端准备，输出文件必须写入 `manifest.outputFile`，stdout 只输出小型摘要 JSON。

## Scope

本 skill 只服务商务标 S3 缺口处理。不得读取或写入技术标 workspace，不得复用技术标 `gap_plan` schema，不得调用或修改 `bid-tech-gap-planner`。

核心目标：

- 以 S2 已确认商务目录为目录主视图全集。
- 以商务响应件任务作为执行单元。
- 回挂商务解析阶段已生成的承诺函/承诺书、商务附件模板、商务评分标准。
- 用商务素材库/Wiki/素材索引推荐候选材料。
- 输出可由前端审核、补料、选择素材，并可被 S4 商务标生成消费的 `business_gap_plan.v1`。

## Inputs

manifest 至少包含：

- `projectId`
- `projectName`
- `bidType`，必须为 `商务标`
- `workDir`
- `tocJsonPath`
- `parseResultPath`
- `businessWikiDir`
- `materialScope`
- `materialIndex`
- `selectedBusinessTurbineModel`
- `outputFile`

可选输入：

- `projectIdentity`
- `existingArtifacts`
- `statePath`

## Output

输出 schema 为 `bid-business-gap-plan-v1`，顶层必须包含：

- `schemaVersion`
- `projectId`
- `projectName`
- `bidType`
- `generatedAt`
- `views`
- `summary`
- `moduleGroups`
- `tocRefs`
- `tasks`

每个 task 至少包含：

- `id`
- `taskKey`
- `title`
- `moduleKey`
- `taskType`
- `decision`
- `status`
- `sourceType`
- `tocTarget`
- `assemblyMode`
- `materialUsage`
- `fillPlan`
- `selectedEvidenceSegments`
- `displayOrder`
- `fingerprint`
- `updatedAt`

## Planning Rules

### Directory Coverage Rule

`tocRefs` 必须覆盖 `tocJsonPath.items[]` 中所有目录项。不要只输出缺口项，不要只输出有素材项。若不能覆盖，命令必须失败。

### Execution Unit Rule

商务标以响应件任务为执行单元：投标函、授权书、承诺书、报价表、证书、回单、协议、业绩支撑、评分证明等都应表达为独立 task。

默认规则：

- 父目录只做组织展示。
- 叶子目录生成任务。
- 没有子项的父目录也生成任务。
- 一个 task 默认只落位到一个 `tocTarget`。
- 同一目录可绑定多个 task，但第一版不把同一 task 落到多个目录。

### Assembly Intent Rule

S3 是装配决策层，必须为每个 task 明确 S4 的执行意图。S4 只执行该意图，不应重新自由判断素材用途。

`assemblyMode` 取值：

- `template_fill_docx`：使用素材库模板底稿或解析附件模板，并用项目事实表填字段。
- `table_fill_from_material`：使用空表模板、项目事实表和素材证据填表。
- `attach_whole_file`：完整附件引用或整份 Word 合入，适合协议、评分标准、说明附件。
- `embed_scan_or_image`：将证书、回单、保函、图片或 PDF 扫描件嵌入正文。
- `extract_and_summarize`：以素材/清洗稿为主输入，结合证据片段定位和项目事实表，供 S4 提取总结、转写为当前章节正文。
- `extract_segment`：只引用素材中的证据片段摘要、页码/位置和原件引用，不做提取总结。
- `ai_draft`：S3 已判断可由 AI 起草，生成受控草稿。
- `manual_upload`：兼容旧数据。人工补料是材料来源，不应作为新任务的优先装配方式。

`materialUsage` 记录 Wiki 或规则推导出的素材用法，例如 `fill_template`、`fill_table`、`attach_whole`、`embed_scan`、`extract_and_summarize`、`extract_segment`。

`fillPlan` 记录 S4 所需输入、输出产物类型、是否依赖项目事实表、是否依赖素材证据。

`selectedEvidenceSegments` 记录已经命中的 Wiki/素材证据片段。若 `assemblyMode=extract_segment`，必须尽量填充该字段；否则需要追加 `segment_location_required` 风险。若 `assemblyMode=extract_and_summarize`，该字段作为提取总结的定位锚点，不代表只粘贴该片段。

### Module Groups

固定使用 6 个一级模块：

1. `base_documents_guarantees`：基础响应文书与担保文件。
2. `structured_response_tables`：报价与结构化响应表。
3. `qualification_compliance_certificates`：主体资格、合规信用与专题证书。
4. `enterprise_finance_supply`：企业能力、财务与供货保障。
5. `performance_cooperation_support`：业绩、合作与专项支撑。
6. `commitments_and_notes`：承诺函与其他说明。

`03` 模块可使用二级分组：

- `subject_qualification`
- `compliance_credit`
- `special_certificates`

### Source Rules

任务来源分为：

- `toc_fixed`：来自商务目录的固定响应件。
- `parser_explicit`：来自商务解析明确要求。
- `parser_semantic`：来自商务解析语义推断，必须加复核风险。
- `material_recommendation`：来自 Wiki/素材推荐，不应单独新建任务。
- `manual`：人工补充。

### Commitment Rules

解析阶段已经生成的承诺函/承诺书不应重新生成，而应回挂到对应 task 的 `resolvedArtifacts`。

回挂顺序：

1. 按 `title` / `normalizedTopic` / `placementHint` 命中具体目录节点。
2. 命中不到时，挂到“投标人需要说明的其他内容”或 `06-承诺函与其他说明` 模块。
3. 仍无法判断时，标记 `manual_placement_required`。

同一解析承诺函产物不得重复挂载到同一任务。

技术承诺过滤和承诺主题去重主要由商务标 S1 解析 skill 完成。S3 只做边界风险提示，不重新生成或重新去重。

### Certificate Rules

证书任务必须关注：

- 有效期。
- 项目所用机型。
- 机型别名、平台、容量等级。
- 大部件名称、部件型号、适用范围。

机型认证证书、大部件型式认证证书必须显式建任务，不能被普通资格证书覆盖。

### Decision Rules

- `ready`：已有正式产物或已确认可用材料。
- `fill_required`：需要基于模板、变量或解析结果生成/填写。
- `material_required`：缺正式材料，需要上传或选择素材。
- `review_required`：已有候选或解析生成稿，但需人工复核。

### Risk Flags

常用风险：

- `missing_material`
- `expiry_check_required`
- `semantic_match_only`
- `customer_specific`
- `project_specific`
- `duplicate_candidate`
- `technical_boundary_risk`
- `parser_generated_unconfirmed`
- `manual_placement_required`
- `section_module_conflict`
- `parser_inferred_mapping`
- `model_mismatch`
- `model_fit_review_required`
- `manual_model_input`

## Stdout Summary

stdout 必须是 JSON，例如：

```json
{
  "schemaVersion": "bid-business-gap-plan-v1",
  "outputFile": "/data/documents/PRJ-0001/business-workspace/gaps/business_gap_plan.json",
  "tocRefCount": 0,
  "taskCount": 0,
  "coverageStatus": "complete",
  "summary": {}
}
```
