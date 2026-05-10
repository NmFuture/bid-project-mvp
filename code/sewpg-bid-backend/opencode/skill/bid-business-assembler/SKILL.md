---
name: bid-business-assembler
description: 商务标 S4 生成标书。输入已确认商务目录、business_gap_plan、项目事实表、商务解析产物、商务素材/Wiki 导出，输出商务投标文件 docx、装配计划、装配报告和待复核清单。只服务商务标，不读取技术标 workspace，不创造报价/证书/授权等事实。
allowed-tools: [Read, Glob, Grep, Bash, Write, Edit]
---

# Business Bid Assembler

## Project Integration Contract

在 `bid-project-mvp` 中，本 skill 的命令入口是：

```bash
businessassemble <manifest>
```

也支持本地 runner：

```bash
python scripts/run_from_manifest.py --manifest <manifest> --response summary
```

后端负责准备 manifest。本 skill 必须把最终 Word 和审计产物写入 manifest 指定路径，stdout 只输出小型 JSON 摘要。

## Scope

本 skill 只服务商务标 `S4 生成标书`。

必须遵守：

- 不读取或写入 `technical-workspace`。
- 不调用 `bid-tech-assembler`。
- 不复用技术标 `gap_plan` schema。
- 不创造报价、日期、证书编号、授权人、业绩事实、承诺事实。
- 缺失值写占位符 `[待填写：xxx]`。
- 所有待人工判断项写入 `business_needs_review.md`。
- PDF、图片、扫描件应尽量嵌入最终 Word，失败时才退化为附件引用。
- 商务评分标准必须进入最终 Word。

## Inputs

manifest 至少包含：

- `projectId`
- `projectName`
- `bidType`，必须为 `商务标`
- `workDir`
- `tocJsonPath`
- `businessGapPlanPath`
- `projectFactTablePath`
- `parseResultPath`
- `materialLibraryDir`
- `outputFile`

可选：

- `businessWikiDir`
- `templateFile`
- `options`

## Output

必须输出：

- `outputFile`：商务投标文件 docx
- `business_assembly_plan.json`
- `business_assembly_report.md`
- `business_needs_review.md`
- `attachment_manifest.json`
- `field_fill_report.json`

stdout summary 格式：

```json
{
  "schema_version": "bid-business-assembly-v1",
  "outputFile": "/data/documents/PRJ-0001/business-workspace/s4_assembly_workdir/商务投标文件.docx",
  "assemblyReport": "/data/documents/PRJ-0001/business-workspace/s4_assembly_workdir/business_assembly_report.md",
  "needsReview": "/data/documents/PRJ-0001/business-workspace/s4_assembly_workdir/business_needs_review.md",
  "planFile": "/data/documents/PRJ-0001/business-workspace/s4_assembly_workdir/business_assembly_plan.json",
  "attachmentManifest": "/data/documents/PRJ-0001/business-workspace/s4_assembly_workdir/attachment_manifest.json",
  "fieldFillReport": "/data/documents/PRJ-0001/business-workspace/s4_assembly_workdir/field_fill_report.json",
  "summary": {
    "sectionCount": 0,
    "assembledCount": 0,
    "placeholderCount": 0,
    "reviewRequiredCount": 0,
    "embeddedAttachmentCount": 0
  }
}
```

## Assembly Rules

1. 以 S2 商务目录为唯一章节骨架。
2. 每个目录节点至少生成一个标题。
3. 优先使用 S3 `resolvedArtifacts`。
4. 必须读取 S3 task/artifact 的 `assemblyMode`，按 S3 决策执行，不得把所有材料无差别拼接。
5. 已选素材副本、上传补料可以直接装配，但装配方式取决于 `assemblyMode`。
6. 投标函、授权书、廉洁承诺等格式件的来源优先级：素材库模板底稿 > 解析附件模板 > runner 基础稿。
7. 项目事实表未确认也允许生成，但必须写入待复核清单。
8. S3 未完全确认也允许生成，但必须写入待复核清单。
9. 商务评分标准必须进入最终 Word；目录无明确位置时，落入“投标人需要说明的其他内容”或文末评分标准章节。
10. 图片/PDF/扫描件尽量嵌入 Word。PDF 通过 PyMuPDF 按页渲染为图片后插入。
11. `assemblyMode=extract_segment` 时，只输出证据片段摘要、页码/位置和原件引用；第一版不整份合入大材料。
12. 无法合并或嵌入的材料，在正文保留附件引用，并写入 `business_needs_review.md`。

## Failure Policy

- 缺少目录 JSON、gap plan 或输出路径：失败。
- 文件缺失：不失败，生成占位和复核项。
- PDF 转图失败：不失败，退化为附件引用。
- docx 合并失败：不失败，退化为附件引用。
