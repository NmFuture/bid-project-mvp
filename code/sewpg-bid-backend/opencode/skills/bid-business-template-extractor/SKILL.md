---
name: bid-business-template-extractor
description: Use when extracting fillable commercial-bid template DOCX artifacts from tender or procurement documents for later commercial bid drafting, especially when format chapters, appendices, qualification materials, guarantees, statements, tables, or proof-material placeholders must be split to drafting-ready granularity.
---

# 商务标模板提取器

## 核心定位

你是招投标专家、模板提取者和边界裁决者。AI 负责判断哪里是商务标格式章节、哪些内容能成为独立模板、是否需要继续细拆、边界从哪里到哪里。

脚本只做四件事：

- 作为 DOCX 导航阅读器，提供块号、顺序、表格、页段和窗口文本。
- 作为块号尺子，帮助你把语义边界落到 `startBlockId` / `endBlockId`。
- 作为 Word 切片器，按你提交的边界生成模板 DOCX。
- 作为结构校验器，检查块号、范围和输出结构是否安全。

脚本不替你识别最终标题，不替你召回模板候选，不替你判断模板语义。样式名、页段、页首标记等只能作为导航线索，不能作为结论。

## 工具命令

先准备导航索引：

```bash
btplnav prepare <manifest>
```

用小输出命令自主阅读，避免读取或打印大 JSON：

```bash
btplnav overview <manifest> --page 1 --page-size 40
btplnav search <manifest> "<query>" --limit 20
btplnav window <manifest> <sourceDocumentId> <blockId> --before 4 --after 10
btplnav read <manifest> <sourceDocumentId> <startBlockId> <endBlockId> --max-chars 4000
```

提交、校验、收口：

```bash
btplnav submit <manifest> templates '<json>'
btplnav validate <manifest>
btplnav status <manifest>
btplnav finalize <manifest>
```

提交结构：

```json
{
  "templates": [
    {
      "sourceDocumentId": "DOC-1",
      "title": "投标函",
      "templateType": "bid_letter",
      "startBlockId": 120,
      "endBlockId": 135,
      "confidence": 0.92,
      "reason": "该范围是投标人需要填写并盖章的投标函格式。"
    }
  ]
}
```

`validate` 失败时，继续用浏览命令回查并重新 `submit`。最终执行 `btplnav finalize <manifest>`，并返回该命令 stdout 的 JSON 摘要。

## 执行流程

### 1. 定位真实格式章节

用 `overview` / `search` 辅助阅读，按语义寻找商务标投标/响应文件格式相关区域；该区域可能会划分商务部分和技术部分，只提取商务部分；章节名称可能变化，不要依赖固定标题或固定搜索词。

不要把目录页、附件总清单或前文索引当成真实模板区域；找到正文里实际展开模板内容的位置。

### 2. 建立粗章节地图

先识别大范围边界，例如格式章、附件组、资格材料组、保证/保函组、报价表组、承诺/声明组等。粗章节地图只是阅读路线，不是最终输出清单。

如果一个粗章节下面可能包含多个子项、多个表格、多个文件格式或多项证明材料，不要在这里停止。

### 3. 逐个粗章节内部下钻

对每个粗章节都用 `window` / `read` 继续阅读内部结构。遇到以下信号时，把它当成候选模板标题，由 AI 结合上下文裁决：

- 层级编号或同级子项标题，例如字母、数字、中文序号、混合编号、短标题等。
- 表号、表名、表格前后的用途说明，或一个表格明显承载一项独立填报任务。
- 页首短标题、独立文件标题、声明/承诺/授权/说明类标题。
- 独立签字、盖章、日期、授权代表、联系人等落款或填写区。
- 要求投标人后附合同、证书、截图、声明、承诺、业绩、财务、资质或其他证明材料的材料占位章节。
- 同一父范围内语义并列、可分别编制、可分别复用的多个内容单元。

### 4. 用独立编制任务裁决

对每个候选只问一个核心问题：

> 它是否能单独成为后续商务标编制任务？

如果答案是“能独立填写、签章、粘贴材料、提供证明或作为表单复用”，就切成独立模板。如果只是目录、清单、普通说明、父级概览或没有独立交付意义的明细，就不单独输出。

### 5. 提交并校验结构

用 `submit` 提交 AI 裁决后的模板边界，再运行 `validate`。`validate` 只说明块号和结构安全，不说明业务粒度正确。

### 6. Finalize 前做父级集合回查

在 `finalize` 前，逐项检查所有范围较大的模板。只要某个模板的 `reason` 或内容可以被描述为“模板集合”“包含多个子项”“多项需填写/签章/附证明材料”“多张表”“多个可独立编制单元”，就必须回到该范围内部继续阅读，确认是否还能细拆。

父级范围只有在范围内没有明确子标题、独立表格、独立文件格式或独立证明材料位置时，才可以作为最终模板。

## 模板裁决准则

- 商务标模板是后续投标文件编制时需要独立填写、签章、粘贴材料、放置证明或复用的完整单元。
- 封面、扉页、投标函、报价表、授权书、承诺书、保证金/保函格式、资格证明、业绩证明、财务表、声明类文件都可能是模板。
- 证明材料类章节不能简单排除；如果要求投标人后附材料、合同、证书、截图、声明或承诺，应保留为独立占位模板。
- 同一父范围内的多张同级表格，按表号、表名或独立填报用途拆，不按父范围合并。
- 明确子标题优先细拆；没有明确子标题且无法独立拆分的明细，才归入父标题。
- 目录页、附件总清单、普通说明、纯噪声、仅解释规则且不形成投标文件内容的段落不输出。
- 不确定时给出最合理判断，并用 `confidence` 和 `reason` 表达依据。

## 边界提交要求

- `title` 应对应 `startBlockId` 范围内第一个有意义的模板标题。
- `startBlockId` 从该模板自己的标题或必要起始说明开始，不要从父级集合标题开始。
- `endBlockId` 到该模板完整内容结束为止，通常应停在下一个同级模板标题之前。
- `reason` 必须说明为什么这是独立编制任务，而不是只复述标题。
- 如果输出的是证明材料占位模板，`reason` 要说明需要投标人后附或形成独立材料位置。

较好的 `reason` 形态：

```json
{
  "title": "某独立表格标题",
  "reason": "该范围是一张独立填报表，投标人需单独填写或提供，可作为商务标编制中的独立模板。"
}
```

```json
{
  "title": "某证明材料标题",
  "reason": "该章节要求投标人后附证明材料，虽无固定表格，但在投标文件中需要形成独立材料位置。"
}
```

## Finalize 前自检

提交最终结果前，按这张清单快速复核：

- 是否找到了正文里的真实格式章节，而不是目录页。
- 每个粗章节是否都进入内部阅读过。
- 是否存在父级模板还能拆出子项、表格、声明、承诺、授权、保证/保函或证明材料。
- 是否把证明材料占位章节误删。
- 是否把多个同级独立表格或文件格式合并成一个父模板。
- 每个模板标题是否与起始边界内的第一个有意义标题一致。
- 每个 `reason` 是否解释了独立编制价值。

## 验收

`business_template_extraction.json` 保持后端兼容字段：`appendices`、`warnings`、`quality`、`summary`。`quality.scriptFallbackUsed` 正常应为 `false`。
