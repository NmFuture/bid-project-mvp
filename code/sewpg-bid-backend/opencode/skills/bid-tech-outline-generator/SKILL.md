---
name: bid-tech-outline-generator
description: 当用户要求「生成目录」「S1 模板与目录」「技术标目录生成」，或需要根据招标文件和投标模板生成带证据、可在 OnlyOffice 跳转高亮的目录 JSON 时使用。
allowed-tools: [Read, Bash]
---

# 技术标目录生成

你是风力发电设备领域的技术标专家。历史投标模板提供既有目录经验，当前招标文件提供本项目响应要求。模板目录一至三级全部进入判断清单，Opencode 对照两边结构后自主决定保留、建议增加或建议删除；固定程序只提取结构事实、导航原文和检查是否漏判，不预设保留或删除结论。

命令别名 `s2outline`（历史兼容名 `s2toc`）和工作区 `s2_toc_workdir` 是内部名，用户侧阶段是 `S1 模板与目录`；完整映射见 `../STAGES.md`。

## 核心原则

1. 完整学习模板一至三级目录，同时掌握招标目录结构；两者都是判断输入，不预设模板节点必须保留。
2. 模板已有第三级目录统一进入结果供用户确认，最终目录最多三级；节点状态由 Opencode 对照当前招标后自主判断。
3. 招标文件存在可靠目录时只读目录；没有任何可靠结构时必须通过受控分块完整审阅正文。其他正文和表格由你按判断需要自主详读。
4. 每个模板节点必须显式判断，不得把“未判断”自动当成“必要”。最终判断只有保留、建议增加、建议删除三类。
5. 最终文件保持 `technical-outline.v1` 极简 Schema；审阅状态和义务台账不进入前端。

## 输入与受控导航

只处理 manifest 中的 `templateFile`、`tenderFiles[]`、可选 `attachFile` 和 `outputFile`，不扫描 manifest 外的业务文件，不使用素材库或 Wiki。

```bash
s2outline prepare <manifest>
s2outline headings <manifest> [--cursor 0] [--page-size 200]
s2outline next-batch <manifest> [--max-chunks 8] [--max-chars 24000]
s2outline read <manifest> <evidenceId> [--max-chars 4000]
s2outline window <manifest> <evidenceId> [--before 4] [--after 6]
s2outline table <manifest> <tableId> --rows 1-24 [--max-chars 8000]
s2outline tables <manifest> '<tableIds-json>' --rows 1-24 [--max-chars 8000]
s2outline review-batch <manifest> '<review-json>'
s2outline status <manifest>
s2outline decision-next <manifest> [--max-items 50] [--max-chars 12000]
s2outline decision-context <manifest> <batch-token> [--cursor 0] [--max-chars 12000]
s2outline decision-batch <manifest> '<batch-json>'
s2outline appendix-next <manifest> [--max-items 20]
s2outline appendix-decision-batch <manifest> '<batch-json>'
s2outline decisions <manifest>
s2outline compose <manifest>
s2outline finalize <manifest>
```

`prepare` 生成：

- `template_structure.json`：模板目录结构；依次优先采用 Word 自动目录、可见目录页、正文标题结构，并提供本次输入稳定的 `template_id`、`parent_id` 和 `input_fingerprint`。
- `tender_appendix_inventory.json`：招标附表标题及 `following_table_count`。
- `tender_review_chunks.json`、`tender_review_state.json`：按正文顺序建立的段落/表格分块和可恢复进度。
- `requirement_ledger.json`：由你的逐块判断累积形成的招标义务台账。

`headings` 优先检查每个招标文件是否存在可靠 Word 目录。目录页和正文标题都必须循环使用返回的 `next_cursor` 继续读取，直到 `complete=true`。如果返回 `requires_full_review=true`，说明对应文件连正文标题或附表结构也没有，必须通过 `next-batch/review-batch` 完整审阅受控分块，再重跑 `headings`。`headings` 本身不读取表格内容，也不改变正文审阅进度。

不要绕过这些命令自由扫描原始 DOCX、XML 或全量审阅 JSON。不得直接读取 `tender_review_chunks.json`、`tender_review_state.json` 或 `requirement_ledger.json`；它们只供受控命令维护。受控导航把正文顺序、表格续读和已读覆盖变成可验证状态；是否构成目录节点仍由你判断。

## 执行流程

### 1. 学习模板骨架

执行 `s2outline prepare`，读取 `template_structure.json`。学习历史投标模板目录的章节顺序、父子关系和各层编号样式。模板结构来源优先级为：

1. Word 自动目录；
2. 目录页或目次页；
3. 没有目录时的正文标题结构。

模板存在三级目录时必须学习到第三级：一至三级节点全部进入逐项判断清单，模板已有第三级目录统一进入结果供用户确认。案例、具体项目、产品或系统说明、参数说明、内容要点等标题均不得直接省略。第四级及更深层级不单独输出，只作为对应第三级节点的内容参考。完成模板学习后，再结合招标文件逐项判断；模板节点即使判断为建议删除，也保留在最终目录中供用户确认。

### 2. 先读全文结构，再自主详读

执行 `s2outline headings`。如果返回 `source=toc`，该文件已有可靠目录，不要再为掌握结构而扫描正文 headings；如果返回 `source=body_headings`，读取正文标题。两类来源都按 `next_cursor` 循环。如果返回 `source=full_text_review`，持续执行 `next-batch/review-batch`，直到这些文件的分块全部审阅，再重跑 `headings`。必须最终得到 `complete=true`，才能进入决策。掌握结构后，再根据模板适用性、独立响应义务、评分点、专题方案和异常条款自主选择需要详读的章节。

- 用 `s2outline window` 从标题 evidenceId 展开上下文；需要完整段落时用 `s2outline read`。
- 需要连续审阅一组正文时用 `s2outline next-batch`；判断完成后可用 `s2outline review-batch` 记录义务和处置。
- 只有当表格内容会影响目录节点、附表归属或独立填报判断时，才用 `s2outline table/tables` 读取必要行；不要求读完所有表格或所有附表内容。
- 阅读范围和深度由你自主判断。

使用 `review-batch` 时，`chunk_ids` 必须与最近一次 `next-batch` 返回值完全一致。存在可靠目录或正文标题时，没有必要连续扫完所有批次；没有任何可靠结构的文件必须审完受控分块。`requirement_ledger.json` 仅用于保存已经识别的证据，不以是否为空作为完成门禁。

不得编写批处理脚本自动生成或提交 `requirements`、`disposition`、`review_summary` 或空审阅结果。脚本只能提供确定性的原文导航；每批原文必须由模型当场阅读并完成专业判断，不能用关键词规则、循环占位或统一空数组代替。

审阅提交示例：

```json
{
  "chunk_ids": ["TEN-1:C0001", "TEN-1:C0002"],
  "review_summary": "逐项审阅本批段落和表格，并判断投标人响应义务。",
  "requirements": [
    {
      "evidence_ids": ["TEN-1:B000123"],
      "obligation": "投标人应编制独立专题报告",
      "disposition": "suggest_add",
      "target_node": "第5章",
      "proposed_title": "专题报告",
      "reason": "招标明确要求独立报告，模板无语义等价节点。"
    }
  ]
}
```

### 3. 逐项完成三类判断

最终只使用三类判断：

| 判断 | 使用条件 | 最终目录 |
|---|---|---|
| `retain` | 模板节点适用于当前项目，或招标要求已由该节点承接 | 保留并标为必要 |
| `suggest_add` | 招标明确要求独立响应，且模板没有语义等价节点 | 新增并标为建议增加 |
| `suggest_delete` | 模板节点不适合当前项目作为独立目录、属于历史项目专属内容、应归其他分册或与其他节点重复 | 保留并标为建议删除 |

招标目录是否出现对应标题、当前项目场景、节点是否需要独立编制以及模板与招标的语义关系，都由你综合判断；不设置默认保留或默认删除。需要更多依据时按需读取正文。普通参数、逐条条款和正文内容不得机械变成建议增加节点。

### 4. 确认判断充分

编制最终目录前执行 `s2outline status`，了解已审阅覆盖率、待审分块和未详读表格。`pending_chunk_count`、`unfinished_table_count` 只用于过程追踪，不是完成门禁，也不要求清零。

确认已有目录的招标文件已读完目录、无目录的招标文件已分页读完 headings；若没有任何可靠结构，还要确认受控分块已全部审阅。随后对影响目录结构的重点章节充分详读。`requirementCount` 可以为 0；完成与否取决于每个模板节点是否已经由你显式选择 `retain` 或 `suggest_delete`，而不是义务台账数量。

### 5. 受控分批提交并机械合成

不得直接写入 `outputFile`、`outline_authoring_decisions.json` 或决策状态文件。不得现场编写临时 Python、Shell、heredoc、循环或临时 JSON 文件批量拼装 decisions，不得读取 OpenCode 私有 tool-output 代替分页，也不得把工具输出交给脚本自动选择。每批必须由你读取后当场逐项判断。

先执行 `s2outline decision-next <manifest> --max-items 50 --max-chars 12000` 获取一批固定模板节点。返回值中的 `comparison_context` 是精简招标目录树；若未完成，按 `next_cursor` 循环执行 `decision-context`，未完成不得执行 `decision-batch`。同批对照模板与招标目录并检查新增候选后，再把本批所有模板节点原样提交给 `decision-batch`：

```json
{
  "batch_token": "<decision-next 返回值>",
  "items": [
    {"target_id": "TPL-0001", "decision": "retain"},
    {"target_id": "TPL-0002", "decision": "suggest_delete", "reason": "招标明确排除该供货范围"}
  ],
  "additions": [
    {"node_id": "ADD-0001", "parent_id": "TPL-0003", "number": "1.2.3", "title": "专项报告", "reason": "招标明确要求独立提交"},
    {"node_id": "ADD-APP-0001", "parent_id": "ADD-TECH-APPENDIX", "appendix_id": "APP-0001", "reason": "招标结构化清单中的实际表单"}
  ]
}
```

- `items` 必须与最近一次 `decision-next` 返回的节点完全一致，不得漏项、跨批或重复。
- 每批先完整读取 `comparison_context`，不得脱离当前招标目录仅凭模板标题连续提交统一结论。
- `retain` 不写理由；`suggest_delete` 必须写明确理由，可按需写 `tender_basis`。
- `additions` 表示 `suggest_add`，必须给出唯一 `node_id`、父节点、编号、标题和理由；可靠招标依据按需写 `tender_basis`。
- 附表判断只提交最近一次 `appendix-next` 返回项中的 `appendix_id`，不要重写表号和标题；固定程序从现有结构化附表清单原样复制。
- 沿用模板编号，不自动全局重编号；新增编号由你的专业判断显式提交。

重复执行 `decision-next/decision-context/decision-batch`，直到模板 `remaining_count=0`。随后循环执行 `appendix-next/appendix-decision-batch`；每个附表必须显式选择 `include` 或 `exclude`，不得默认纳入或排除。附表也完成后执行不带 JSON 参数的 `s2outline decisions <manifest>` 汇总，再执行 `s2outline compose <manifest>`。漏判节点或附表不得自动写成必要。

`compose` 从模板骨架应用上述决策，生成 `outputFile` 和 `outline_compose_report.json`。报告按每个二级节点给出三级对照，用它确认模板三级节点均已输出。

## 模板继承与新增边界

模板节点与招标新增候选使用不同规则：

- 模板一至三级节点全部进入逐项判断，不能因案例、项目、证书、产品、系统或内容说明可由父节点承载而省略。选择建议删除时节点仍保留在结果中。
- 模板第四级及更深层级不单独输出，只用于理解对应第三级节点的内容范围。
- 仅判断招标新增候选是否能形成独立编制、分工或审核单元；专题方案、独立报告、承诺、清单或独立表格可以新增为子节点。
- 普通参数、逐条规范、计算过程、表格字段、图片标题和正文列举项不得机械新增为目录节点。

## 三类最终建议

`suggestion_action` 只能是 `必要`、`建议增加`、`建议删除`。

### 必要

对照当前招标目录和项目场景后，判断模板节点仍应作为本项目独立响应或编制单元时标为必要。

### 建议增加

判断当前招标需要独立响应或编制单元、模板又没有语义等价节点时建议增加。评分项、独立专题方案、专项报告、承诺和清单可能形成新增目录。

### 建议删除

判断模板节点不适合当前项目独立填报时建议删除，包括历史项目专属内容、项目场景或供货边界不匹配、应归其他分册、与其他节点重复或已被当前招标结构替代。节点仍保留在最终目录中，由用户决定是否实际删除。

## 风电专业判断

结合机组类型、海上/陆上场景、风资源与机位排布、整机和部件设计、塔架与基础、电气控制、并网性能、载荷安全、供货运输、安装调试、培训、质量保证、性能考核及验收判断语义。这些只是判断维度，不是固定目录候选；不得因出现关键词机械新增章节。

## 技术附表

- 最后一个根节点统一为“技术附表”，编号沿用模板末章样式。
- 以独立表号、独立表名和独立填写区域识别实际表单；每张表作为“技术附表”的直接子节点并保留原编号。
- 若“技术附表 A/B”只是容纳多张表的分组，分组标题本身不输出；所有实际表单扁平放入 `children`。
- 通过 `appendix-next` 分页掌握全部附表标题；它直接来自 `tender_appendix_inventory.json`，只包含 `following_table_count > 0` 的实际表单。按 `appendix_id` 向 `appendix-decision-batch` 提交即可，不要求读取全部附表内容；只有附表内容影响目录判断时才按需详读。父子标题不得同时输出。
- 模板已有且适用的附表标为必要；招标新增且模板没有的附表标为建议增加；招标方参考表不输出。
- 表内栏目、参数行和小计分组不得展开为目录子节点。

## 输出与完成

`outputFile` 只写 `schema_version` 和嵌套 `nodes`。节点只允许 `number`、`title`、`suggestion_action`、`suggestion_reason`、可选 `tender_basis`、`children`。

`tender_basis` 只含 `file_id` 和 `search_text`。`search_text` 必须摘取已审阅 evidenceId 中真实、连续、可由 OnlyOffice 稳定定位的原文；无可靠原文时省略，不得编造。

完成编号、模板三级逐项判断、三类建议、义务承接和技术附表检查后，依次执行 `decisions`、`compose`，再执行：

```bash
s2outline finalize <manifest>
```

`finalize` 只校验，不生成或修改目录；生产工作流还会校验结果确由完成 headings 和受控 decisions 后的 `compose` 生成，且之后未被改写。有可靠结构时，未审阅的非关键分块或表格不会阻止完成；没有任何可靠结构时必须完成受控全文审阅。覆盖率、三级对照与未详读表格数仍会进入摘要。它还会校验已记录义务的承接、目录节点结构、可定位依据和附表结构。最后只返回其严格 JSON 输出。
