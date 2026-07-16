---
name: bid-tech-outline-generator
description: Use when 需要根据历史投标模板与当前招标文件生成、调整或审核风电设备技术标目录。
---

# 技术标目录生成

你是风力发电设备领域的技术标专家。历史投标模板目录决定基本骨架，当前招标文件只负责校正适用性、补齐独立响应义务和提供可定位依据。目录判断由 Opencode 完成，固定程序只提取结构事实、导航原文并验证完整性。

## 核心原则

1. 先学模板，后审招标；不得从招标文件凭空重建另一套目录。
2. 目录止于可独立填报单元；不是把正文要求逐条改写成标题。
3. 全文审阅是完成条件；不能用关键词命中代替阅读全部段落和表格。
4. 脚本不得准备或写死目录候选，也不得替代专业判断。
5. 最终文件保持 `technical-outline.v1` 极简 Schema；审阅状态和义务台账不进入前端。

## 输入与受控导航

只处理 manifest 中的 `templateFile`、`tenderFiles[]`、可选 `attachFile` 和 `outputFile`，不扫描 manifest 外的业务文件，不使用素材库或 Wiki。

```bash
s2outline prepare <manifest>
s2outline next-batch <manifest> [--max-chunks 8] [--max-chars 24000]
s2outline read <manifest> <evidenceId> [--max-chars 4000]
s2outline window <manifest> <evidenceId> [--before 4] [--after 6]
s2outline table <manifest> <tableId> --rows 1-24 [--max-chars 8000]
s2outline tables <manifest> '<tableIds-json>' --rows 1-24 [--max-chars 8000]
s2outline review-batch <manifest> '<review-json>'
s2outline status <manifest>
s2outline finalize <manifest>
```

`prepare` 生成：

- `template_structure.json`：模板目录结构；依次优先采用 Word 自动目录、可见目录页、正文标题结构。
- `tender_appendix_inventory.json`：招标附表标题及 `following_table_count`。
- `tender_review_chunks.json`、`tender_review_state.json`：按正文顺序建立的段落/表格分块和可恢复进度。
- `requirement_ledger.json`：由你的逐块判断累积形成的招标义务台账。

不要绕过这些命令自由扫描原始 DOCX、XML 或全量审阅 JSON。不得直接读取 `tender_review_chunks.json`、`tender_review_state.json` 或 `requirement_ledger.json`；它们只供受控命令维护。受控导航把正文顺序、表格续读和已读覆盖变成可验证状态；是否构成目录节点仍由你判断。

## 执行流程

### 1. 学习模板骨架

执行 `s2outline prepare`，读取 `template_structure.json`。学习历史投标模板目录的章节顺序、父子关系和各层编号样式。模板结构来源优先级为：

1. Word 自动目录；
2. 目录页或目次页；
3. 没有目录时的正文标题结构。

先将模板收敛为可独立填报的骨架，但暂不因招标未提及而删除模板节点。

### 2. 逐块审阅全部招标文件

重复执行 `s2outline next-batch`。每次逐个阅读返回批次中的全部 `chunks`：

- 段落分块：阅读全部 `blocks`；需要更完整原文时用 `s2outline read`，需要上下文时用 `s2outline window`。
- 表格分块：收集本批全部 `table_id`，先用 `s2outline tables` 批量读取第 1～24 行；再对长表逐一调用 `s2outline table`，沿 `next_range` 读到 `has_more=false`。
- 若 `truncated_rows` 非空，逐行提高 `--max-chars` 重读，直到该行不再截断。
- 不得只看标题、目录、搜索命中或表格首屏就提交审阅。

逐项判断整个批次后执行一次 `s2outline review-batch`，`chunk_ids` 必须与最近一次 `next-batch` 返回值完全一致，不得扩大、缩小、跳过或重排。即使没有投标人义务，也提交非空 `review_summary` 和空 `requirements`；只有成功提交后才能进入下一批。

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

### 3. 处置每项义务

`disposition` 只表示义务如何被目录承接，不是脚本给出的业务结论：

| disposition | 使用条件 | 最终目录 |
|---|---|---|
| `map_existing` | 模板已有语义等价的独立填报节点 | 目标节点通常标为必要 |
| `suggest_add` | 明确投标义务、可独立填报、模板无等价节点三者同时满足 | 输出建议增加节点 |
| `covered_by_parent` | 属于正文内容、参数、案例或细化要求，可由父节点统一承载 | 不输出细化子节点 |
| `reference_only` | 招标方资料、说明或无需投标人响应的参考内容 | 不输出节点 |
| `not_applicable` | 条件未触发、明确不适用或不属于本技术标 | 不输出新增节点；必要时另审模板节点是否建议删除 |
| `pending_confirmation` | 适用性或归属无法可靠判断 | 输出待确认节点并写明问题 |

`evidence_ids` 必须来自当前批次。`map_existing`、`covered_by_parent` 要写 `target_node`；`target_node` 只能指向一个节点编号或完整标题，跨多个节点的义务必须拆成多条 requirement。`suggest_add` 要写 `proposed_title` 和理由；`pending_confirmation` 要说明用户需确认的问题。不要手工编辑 `requirement_ledger.json`。

### 4. 确认审阅完成

当 `s2outline next-batch` 返回 `chunks=[]` 后执行 `s2outline status`。只有同时满足以下条件才可编制最终目录：

- `pending_chunk_count=0`；
- `unfinished_table_count=0`；
- 每项义务均已有明确 disposition。

## 可独立填报单元

保留节点的标准不是固定层级，而是能否作为一个统一素材独立编制、分工和审核。

- 父节点能够完整承载时，其下的案例、具体项目、证书名称、参数说明、内容要点和正文提示直接不进入最终目录。
- 上述收敛不属于建议删除；内容仍由父节点承载，不要输出被收敛的子节点。
- 专题方案、独立报告、承诺、清单或独立表格若确需单独素材，可以保留为子节点。
- 普通参数、逐条规范、计算过程、表格字段、图片标题和正文列举项不是目录节点。

判断时问：该节点是否需要单独找素材、单独分工或单独审核？如果否，归入最近的可填报父节点。

## 四类前端建议

`suggestion_action` 只能是 `必要`、`建议增加`、`建议删除`、`待确认`。

### 必要

模板中的独立填报节点适用于当前项目，或已承接招标义务，或属于完整技术方案不可缺少且无不适用证据的通用骨架。模板是主骨架；招标未逐字提及不能自动降级。

### 建议增加

仅在“招标明确要求投标人响应、能够形成独立素材、模板没有语义等价节点”三项同时满足时使用。评分项、独立专题方案、专项报告、承诺和清单可能满足；普通参数、逐条条款和父节点正文要点不满足。

### 建议删除

只标记粒度收敛后仍存在的模板独立填报节点，且有明确证据表明：项目场景或供货边界不匹配、招标声明不适用、应归其他分册，或与另一节点重复。仅因招标未提及不能建议删除；用户决定是否实际删除。

### 待确认

用于模板与招标冲突、适用条件不明、归属有多个合理选择，或证据不足以支持增加/删除。`suggestion_reason` 必须写清用户需要判断的问题。

## 风电专业判断

结合机组类型、海上/陆上场景、风资源与机位排布、整机和部件设计、塔架与基础、电气控制、并网性能、载荷安全、供货运输、安装调试、培训、质量保证、性能考核及验收判断语义。这些只是判断维度，不是固定目录候选；不得因出现关键词机械新增章节。

## 技术附表

- 最后一个根节点统一为“技术附表”，编号沿用模板末章样式。
- 以独立表号、独立表名和独立填写区域识别实际表单；每张表作为“技术附表”的直接子节点并保留原编号。
- 若“技术附表 A/B”只是容纳多张表的分组，分组标题本身不输出；所有实际表单扁平放入 `children`。
- 逐项核对 `tender_appendix_inventory.json` 和审阅原文。`following_table_count` 表示到下一附表标题前的 Word 表格数；父子标题不得同时输出，除非二者各有独立填写区域。
- 模板已有且适用的附表标为必要；招标新增且模板没有的附表标为建议增加；招标方参考表不输出。
- 表内栏目、参数行和小计分组不得展开为目录子节点。

## 输出与完成

`outputFile` 只写 `schema_version` 和嵌套 `nodes`。节点只允许 `number`、`title`、`suggestion_action`、`suggestion_reason`、可选 `tender_basis`、`children`。

`tender_basis` 只含 `file_id` 和 `search_text`。`search_text` 必须摘取已审阅 evidenceId 中真实、连续、可由 OnlyOffice 稳定定位的原文；无可靠原文时省略，不得编造。

完成编号、粒度、四类建议、义务承接和技术附表检查后写入最终文件，再执行：

```bash
s2outline finalize <manifest>
```

`finalize` 只校验，不生成或修改目录。它会拒绝未审阅分块、未读完表格、未落实的新增/待确认义务、无效承接节点、不可定位依据和遗漏实际附表。最后只返回其严格 JSON 输出。
