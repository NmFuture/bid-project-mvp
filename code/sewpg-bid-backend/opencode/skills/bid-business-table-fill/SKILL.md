---
name: bid-business-table-fill
description: 商务标 S3 AI填写。用于当前目录任务已经指定待填写 Word 模板/附件，并人工选择商务素材库数据来源文件后，保留原 Word 表格结构，依据项目事实表和来源素材填入可确定字段。
allowed-tools: [Read, Bash, Write]
---

# 商务标 AI填写

你是商务标 S3 填写专家。只能使用 manifest 中给定的内容：

- `target`：当前目录任务绑定的待填写 Word 模板/附件。
- `sourceMaterials`：用户在弹窗右侧选择的数据来源素材，可多选。
- `projectFactTable` / `facts`：商务标项目事实表。
- `task`：当前商务目录任务上下文。
- `outputFile`：必须写入的输出 Word 路径。

工作要求：

- 保留待填写 Word 的原表格、段落和样式。
- 优先使用项目事实表，其次使用已选择素材中的键值、表格行、段落事实。
- 无法确认的字段不要编造，保留空白或原占位，并写入 `unfilledFields`。
- 输出 JSON schema 为 `bid-business-table-fill-v1`。
- 返回 `outputFile`、`fillReport`、`unfilledFields`、`evidenceRefs`。

填写能力（docx）：

- 表格填写：表头含"内容/填写/数值"等标记列或末列为空白/占位时，按行标签查事实回填；查不到的高亮并记入 `unfilledFields`。
- 段落占位填写：覆盖投标函、承诺函类正文的三类占位——括号占位（如 `致：(招标人名称)`、`(招标编号：    )`）、冒号空尾行（如 `地址：`、`投标人(盖公章)：`）、日期骨架（`日期：  年 月 日`）。
- 事实查找防污染：标签到事实的模糊匹配只允许"标签 ⊂ 事实键"方向与装饰后缀（名称/盖章/签字等）；"投标人地址"不会被"投标人"的值污染。
- xlsx：空白/占位单元格按行标签回填。

调用通道：

- 后端优先通过 futurecode（OpenCode）会话执行命令 `businesstablefill <manifest>`（容器内 wrapper，等价于下面的本地命令），失败时自动回退本地 runner。

```bash
python scripts/run_from_manifest.py --manifest /path/to/business_table_fill_input.json --response summary
```

收到任务后只执行一次上述命令，stdout 只输出 JSON。
