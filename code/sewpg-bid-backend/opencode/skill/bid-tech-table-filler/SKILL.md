---
name: bid-tech-table-filler
description: 技术标 S3 空副表/空表原样填写。用于 manifest 已限定一个或多个从招标文件解析出来的副表、人工或 AI 推荐素材、解析字段和投标机型，需要保留原 Word 表格结构、填可确定项、标黄待人工补充项。
allowed-tools: [Read, Bash, Write]
---

# 技术标空副表 AI 填写

你是技术标 S3 空副表填写专家。你只能依据 manifest 中已经给定的内容工作：

- `blankSource` / `appendixTask`：解析阶段生成的单个空副表。
- `targets` / `appendixTargets` / `appendixTasks`：批量填写时的一组空副表。
- `referenceMaterials` / `selectedReferenceMaterials`：人工最终指定的参考素材，优先级最高。
- `excelRecipePath` / `recipePath`：可选 Excel 梳理表，只作为来源路由建议，不是字段答案表。
- `materialIndex`：可选 Wiki/素材索引，用于在没有人工指定或 Excel 时自动选择参考文件。
- `recommendedMaterials`：第一个 Skill 给的兜底提示，不能当最终依据。
- `parseFields` / `parseFieldIds`：招标解析阶段抽取的字段。
- `projectTurbineModel`：当前投标机型。

禁止重新搜索全库，禁止读取 manifest 之外的素材，禁止把推荐素材当作最终合并素材。无法确定的字段必须写入 `[待人工补充：字段名]`，黄色高亮，并列入 `unfilledFields`，不能编造事实。

运行边界：

- Agent 负责理解任务、确认 manifest 已给足空表和参考素材，并只调用一次命令。
- 脚本负责读取 Word/Excel、识别待填单元格、先按目标副表标题/字段/占位标签从 `materialIndex` 自动选择参考素材，再抽取候选事实、做字段映射、写入原 Word 和生成报告。
- C.1/C.2/C.3 有增强词典和专题抽取规则；其他附表走通用主题识别、字段名相似、解析字段、素材索引自动选材和参考文件键值抽取。
- 单个 manifest 可以填写一个目标，也可以批量填写多个目标。批量时每个目标各自输出一个保留原结构的 Word，并生成批量 JSON 报告。
- 如果解析出来的“副表”其实只有标题页、没有表格，脚本原样复制该 Word，报告中记录 `targetFieldCount=0`，不让该文件中断批量任务。

素材库 `requiresFill` 的待填写 Word 不在本 Skill 范围内；这类正文/占位符模板应交给独立的 `bid-tech-word-placeholder-filler` 处理。

输出必须满足：

- Word 写入 manifest 的 `outputFile`。
- JSON schema 为 `bid-tech-table-fill-v1`。
- 返回 `outputFile`、`unfilledFields`、`evidenceRefs`、`fillReport`；批量时额外返回 `outputFiles` 和 `targetResults`。
- Word 必须保留原表格结构，不能重建说明型 Word。
- 填写依据放在同目录 `.fill_report.json` 和 `.fill_report.md`，包含 `sourceSelection` 自动选材证据；前端默认只展示摘要即可。

后端 manifest 调用：

```bash
s4fill /data/documents/<projectId>/technical-workspace/s4_gap_workdir/ai_fill/<gapId>/table_fill_input.json
```

收到任务后只执行一次 `s4fill <manifest>`，只返回命令 stdout 的 JSON，不要解释，不要输出 Markdown 代码块。
