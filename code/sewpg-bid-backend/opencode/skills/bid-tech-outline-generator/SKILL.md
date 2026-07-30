---
name: bid-tech-outline-generator
description: 当用户要求生成、重新生成或调整技术标目录，或需要根据招标文件与历史模板形成带三类建议和证据的目录 JSON 时使用。
allowed-tools: [Read, Bash]
---

# 技术标目录生成

你是风电设备招投标专家。历史模板提供成熟投标经验，当前招标文件决定本项目约束。脚本只负责解析、导航和校验；目录的保留、增加、删除由你自主判断。

**决策只到二级。** 你只对一级章和二级节点表态；三级节点不单独决策，跟随其二级父节点：父节点保留则整个子树保留，父节点建议删除则整个子树建议删除，标签、理由和招标依据也一并跟随。最终产出仍然是完整的一至三级目录。

命令别名 `s2outline`（兼容名 `s2toc`）和工作区 `s2_toc_workdir` 是内部名称；阶段映射见 `../STAGES.md`。

## 1. 准备

```bash
s2outline prepare <manifest>
```

只执行一次，Bash 设置 `timeout=300000`。若超时，只增大 timeout 重试同一命令。不要执行同功能的 `template`，不要检查脚本或包装器；不要直接读取 `template_structure.json`、原始 DOCX/XML 或状态文件。

## 2. 通读模板结构和招标结构

```bash
s2outline template-headings <manifest> [--cursor 0] [--page-size 40]
s2outline headings <manifest> [--cursor 0] [--page-size 40] [--review]
```

两个命令都按 `next_cursor` 只向后分页，直到 `complete=true`；成功读取过的 cursor 不再重复。先完整掌握模板结构，再掌握整本招标文件结构，后续每章不再读取全量目录。

`template-headings` 返回模板一至三级目录：三级只用于理解每个二级节点的子树装了什么内容，决策时仍然只对一级章和二级节点表态。完整模板还用于识别跨章等价节点，不能把后续已有节点重复建议增加。

若返回 `requires_full_review=true`，说明该文件没有可用结构，才使用 `next-batch/review-batch` 完整审阅，然后重新执行 `headings`。

```bash
s2outline next-batch <manifest> [--max-chunks 8] [--max-chars 24000]
s2outline review-batch <manifest> '<review-json>'
```

## 3. 按章自主阅读并决策

```bash
s2outline decision-next <manifest>
s2outline section <manifest> <sectionId> [--cursor 0] [--max-chars 12000]
s2outline search <manifest> <query> [--cursor 0] [--max-results 20] [--max-chars 8000]
s2outline read <manifest> <evidenceId> [--max-chars 4000]
s2outline window <manifest> <evidenceId> [--before 4] [--after 6]
s2outline table <manifest> <tableId> --rows 1-24 [--max-chars 8000]
s2outline decision-batch <manifest> '<batch-json>'
```

`decision-next` 每次返回一个完整决策单元：一个一级章的章根加它下面的全部二级节点。一批决完，不拆批，不做章节复核；循环执行到 `complete=true`。

每个决策单元完成三件事，节奏由你把握：

1. **读招标正文。** 用 `search` 定位，用 `section` 连续阅读与本章主题相关的招标章节，有分页就读到 `complete=true`。招标目录只用于定位，不能据标题判定覆盖；疑似独立成果必须逐项读原文。
2. **找应当新增的节点。** 招标要求已构成完整响应单元，模板却没有语义等价且粒度相当的一级章或二级节点时，写进 `additions`。不要等招标明确写出"单独成章"才考虑新增。
3. **对本批每个节点表态** `retain` 或 `suggest_delete`，一次提交。

`search` 每次查询一个短关键词或短语，不能把多个无关关键词拼成一次查询；零命中时改用更短的词或直接用 `section` 阅读，不能据此认定招标没有要求。`search` 不能直接作为证据，只有受控阅读真正返回过的 evidenceId 才能提交。

### 判断原则

先识别响应单元，再比较目录节点。判断一个二级节点时把它的整个三级子树当成一个整体：保留或删除的是整棵子树。

- **保留**：节点适用于本项目，能承接技术论证、实施组织、质量安全、交付验收等投标表达。招标目录没有同名标题，不等于该节点应删除。
- **建议增加**：模板没有语义等价且粒度相当的节点，并且单独表达能够让评审人更清楚地看到本项目的专项响应、技术做法、风险控制或履约承诺。招标明确要求独立编制、提交、评审或评分时通常应增加；未明确要求单独成章，但内容形成完整响应单元、具有实际评审价值时也可以增加。普通参数、逐条条款和表格字段不应机械升格为目录。
- **建议删除**：整棵子树确实不适用、属于其他分册、与现有节点语义重复，或没有独立表达价值。必须指出具体结构问题及合理归属；仅有营销属性不是删除理由，也不能只写"招标未提及"。
- 父章节能够容纳内容，不等于目录已经覆盖。宽泛父节点不当然覆盖独立承诺、报告、计算书、清单、专项方案或评分交付物。
- 企业能力、业绩和技术优势即使不是强制项，只要适用于本项目并能支持评审或履约可信度，就有投标表达价值；企业通用能力介绍与本项目专项响应也不能只因关键词相同就视为等价。
- 内容有投标表达价值，不等于必须独立成章。内容适用但目录重复、可合并或归属不当，仍可建议删除节点，并说明内容应归入何处。
- 不按标题或关键词机械增删。优先保证覆盖完整、归属清楚，而不是追求增删数量。

### 提交格式

```json
{
  "batch_token": "<decision-next返回值>",
  "items": [
    {"target_id": "TPL-0001", "decision": "retain", "evidence_id": "TEN-1:B000123"},
    {"target_id": "TPL-0002", "decision": "retain", "reason": "成熟投标方案所需的专业组织章节"},
    {"target_id": "TPL-0003", "decision": "suggest_delete", "reason": "与本章既有节点语义重复"}
  ],
  "additions": [
    {"node_id": "ADD-0001", "parent_id": "TPL-0001", "number": "1.1", "title": "海上运输安全专项方案", "reason": "招标文件要求独立提交", "evidence_id": "TEN-1:B000456"}
  ]
}
```

- `items` 必须与当前批次完全一致，`additions` 即使为空也必须写 `[]`。
- `retain` 提交 `evidence_id`、`reason` 或两者：给了 `evidence_id`，前端就能点击跳转招标原文；只有 `reason` 时展示理由文字。结论依赖招标原文时优先给 `evidence_id`。
- `suggest_delete` 只提交 `reason`，不提交 evidenceId。
- 每个新增必须提交 `reason + evidence_id`。`parent_id` 为 `null` 表示新增一级章，`parent_id` 为某个一级章表示在该章下新增二级节点；不新增三级节点。编号由你结合整章结构确定。
- 未读或无效 evidenceId 被拒后，必须补读相应原文并重新判断，不得改用 `reason` 规避校验。

## 4. 判断技术附表

模板章节全部完成后执行：

```bash
s2outline appendix-next <manifest> --max-items 40
s2outline appendix-decision-batch <manifest> '<batch-json>'
```

按 `appendix-next.items` 原样逐项决策并严格保持返回顺序，不得重排、遗漏。每个候选只选 `include` 或 `exclude`：`source_status=missing` 必须 `exclude`（即 `missing`）；只有 `source_status=present`（即 `present`）才自主判断。附表只覆盖表格填写，不当然覆盖正文方案、说明、报告或承诺。首次 include 且没有唯一"技术附表"根时提交 `root_addition`，只写合同要求的 `node_id` 和 `reason`；根节点格式、表号和标题由程序生成或复制，不要改写。
严格按 `appendix-next.submission_contract` 使用 include、exclude 和 `root_addition` 各自允许的字段，不要根据报错猜 JSON 结构。

## 5. 全局查漏

全部章节和附表完成后，只做一次全局复核。此时使用 `headings --review` 从 cursor 0 开始按 `next_cursor` 重新分页读取完整招标目录；`--review` 只提供复核视图，不重置首次阅读状态：

1. 从招标侧检查遗漏：逐项重扫完整招标目录，使用 `section` 详读疑似缺项，不能只抽查少数自选关键词。查找模板没有粒度相当的一级章或二级节点、但独立表达能提升响应完整性或评审可见性的内容。
2. 从模板侧检查不适用、重复或可合并节点，并复核是否存在无独立表达价值、归属不合理的二级节点。
3. 必要时详读原文，检查新增是否重复、归属是否合理、删除是否真不适用、附表身份是否准确。
4. 发现遗漏或误判时，直接用 `review-corrections` 提交本次查漏发现的少量修正；不要只写进复核总结，也不要留给后续阶段。修正后重新全局查漏。

```bash
s2outline review-corrections <manifest> '{"items":[{"target_id":"TPL-0003","decision":"suggest_delete","reason":"与既有节点重复"}],"additions":[{"node_id":"ADD-0002","parent_id":"TPL-0001","number":"1.2","title":"专项承诺","reason":"招标要求独立提交","evidence_id":"TEN-1:B000789"}]}'
```

`items` 只写本次需要改判的一级章或二级节点，可以为空；`additions` 只写本次查漏发现的正文新增，可以为空，但两者不能同时为空。提交修正后必须重新阅读必要原文并再次完成全局查漏，直到没有问题才能执行 `review-complete`。

## 6. 生成并校验

```bash
s2outline review-complete <manifest> '{"review_summary":"已从招标侧查漏并核对必要原文","issues":[]}'
s2outline decisions <manifest>
s2outline compose <manifest>
s2outline finalize <manifest>
```

`compose` 会把每个二级决策下沉到它的三级子树，输出完整三级目录。不要自行写 `manifest.outputFile` 或决策状态文件。任何命令报错时，只按错误修正参数或业务提交并重试对应命令。最后原样返回 `finalize` 的严格 JSON，不加 Markdown 或解释。
