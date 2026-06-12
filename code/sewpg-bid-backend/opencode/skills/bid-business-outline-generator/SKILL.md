---
name: bid-business-outline-generator
description: 当用户要求生成商务标目录、商务标大纲、商务响应目录、投标文件目录结构或 outline.json 时使用。需要先学习历史商务标投标文件的目录层级和顺序，再结合当前招标文件要求匹配 source_text、补强特殊提交材料，并最终只输出 outline.json。
---

# 商务标目录生成 Skill

你是资深标书专家。你的任务是生成商务标目录结构文件 `outline.json`：先学习历史商务标投标文件的目录结构、层级、编号和顺序，再用当前招标文件中的特殊条款、约定、必须承诺项、必须提交材料、废标/资格/符合性/商务评分要求补强目录。

## 项目集成契约

在 `bid-project-mvp` 中执行本 skill 时，入口命令固定为：

```bash
business-outline <manifest>
```

后端通过 `manifest.templateFile` 提供用户上传的历史商务标或商务模板文件。必须使用该文件作为历史商务标来源，不要扫描当前工作目录寻找历史标书，也不要使用 `user_confirmed_inputs.json`。

原生 skill 产物仍然是 `outline.json`，其 `schema_version` 固定为 `business_bid_outline.v1`，顶层包含 `sections[]`。`business-outline <manifest>` 运行器只负责准备输入和候选 JSON 文件，不得写入 `outline.json`，不得写入最终 `sections[]`，也不得作出最终 `required_status` 决策。opencode 负责语义选择、状态判断和保留/延后理由，然后写入 `outline_authoring_decisions.json`；固定的 `scripts/outline_authoring_helper.py` 只负责读取候选、保持 ID、组装/写回 `outline.json`、运行基础校验。为了兼容前端，后端会在 skill 完成后把最终 `outline.json.sections[]` 转换为 `manifest.outputFile`（`bid-toc-json-v1`）。

当后端集成提示调用本 skill 时，必须遵守工具顺序：加载本 skill 后，第一次非 skill 工具调用必须是 Bash 命令 `business-outline <manifest>`。在该准备命令完成前，不得用 read、glob、list、cat、grep 等方式检查 manifest。

`manifest.workDir` 中必须产生或使用以下项目产物：

- `history_bid_outline_inputs.json`
- `tender_map_inputs.json`
- `document_structure_index.json`
- `source_text_candidates.json`
- `outline_authoring_decisions.json`
- `outline.json`

前四个文件只是准备产物，是供 opencode 消费的证据输入和候选集合，不是最终交付物。`source_text_candidates.json` 是排序后的证据候选集，不是目录。辅助脚本给出的 `suggested_required_status` 或 `suggested_reason` 只是建议。只有 opencode 按本 `SKILL.md` 学习历史结构、分析当前招标文件、选择 `source_text`、判断 `required_status` 并写出 `outline_authoring_decisions.json` 后，才能调用固定 helper 生成最终 `outline.json`。不得让 opencode 现场编写临时 Python 脚本来拼装最终目录。

`outline.json.sections[]` 必须保留足够证据供后端转换：至少包含 `title`、`level`、`required_status`、`source_text`，并尽量保留 `source_refs`。`source_refs[]` 中的招标文件依据建议包含 `type: "tender"`、`role: "basis"`，并在 `searchText`、`basisText` 或 `rawText` 中保留可检索文本，以便当前前端展示依据卡片并在 OnlyOffice 中跳转。

最终 section 还必须保留质量门禁使用的证据决策元数据：

- `evidence_scope`：所选候选的范围，例如 `parent_context`、`format_area`、`high_value_area`、`broad_clause`、`history_fallback`。
- `evidence_strength`：`strong`、`medium`、`weak` 或 `fallback`。
- `evidence_category`：所选候选的类别，例如 `scoring_response`、`qualification_requirement`、`format_appendix`、`submission_requirement`。
- `reason`：简要说明为什么选择该 `source_text` 和 `required_status`。

如果 `source_text_candidates.json.items[*].candidates[0]` 存在，并且不是目录页/页码行，也不是 `合计 | 100`、`总计 | ...`、`小计 | ...` 等纯汇总行，应默认使用该首选候选作为 `source_text`，并把它的 `scope`、`evidence_strength`、`evidence_category`、`match_reason` 写入最终 section 元数据。不得仅因为附近有汇总表行，就用汇总行替换强标题或强段落候选。若首选候选本身就是目录项标题或明确的提交材料名称，最终 `source_text` 必须保留该候选。

## 触发场景

当用户要求生成以下内容时，必须使用本 skill：

- 商务标目录
- 商务标大纲
- 商务响应目录
- 投标文件目录结构
- `outline.json`

## V1 边界

V1 只做目录结构判断，最终只输出一个 `outline.json`。

禁止：

- 生成商务标正文。
- 生成 Markdown 目录作为最终交付物。
- 自动生成完整投标文件。
- 输出 `outline.json` 以外的最终交付物。
- 把当前招标文件中的“投标文件格式”“响应文件格式”等不稳定目录块作为顶层 `sections` 的主要来源。
- 无条件把历史投标文件原文作为最终 `source_text`。

## 工作原则

- 历史商务标投标文件是历史经验结晶，是目录结构的优先继承对象。顶层、`children`、`grandchildren` 都要学习并尽量保留，用于继承顺序、层级关系、常见章节名称、子项归属和哪些材料通常单独编排。
- 历史 child / grandchild 默认应保留。只有存在强证据表明该项不适合在目录阶段保留时，才允许删除、延后或合并。
- 不得仅因当前招标文件没有逐字对应 `source_text`、只有宽泛条款覆盖、多个历史子项同属一类要求、标题可被概括表达，或为了让目录更短更整齐，就删除或合并历史 section、child 或 grandchild。
- 当前招标文件 `source_text` 匹配失败，只影响 `source_text` 的选择和 `required_status` 判断，不构成删除历史子项的理由。
- 只有能明确判断为“素材库组装项”、明显不适用于当前项目且有当前招标文件明确依据，或已被另一个更明确的历史目录项完整覆盖的历史子层级，才可在目录生成阶段延后、不保留或合并。
- 无法判断某个历史子层级是否应删除时，优先按“历史经验项”保留，并用 `required_status`、`context` 或 `review_items` 标明当前招标文件证据不足。
- 当前招标文件是当前项目要求的权威来源，也是 `source_text` 的优先来源。
- 从历史目录学习来的每个 section、child 或 grandchild，都必须尽量回到当前招标文件中寻找对应原文。
- 找不到当前招标文件明确原文不代表删除。历史经验项可使用历史投标文件原文作为 `source_text` fallback，但必须说明原因。
- 当前项目补强项的 `source_text` 必须来自当前招标文件，不能来自历史投标文件。
- 顶层 `sections` 原则上保持历史商务标目录结构，不为匹配当前招标文件中的不稳定目录块而重排。
- `review_items` 只记录完成目录判断后仍影响目录项存在、归属或状态的人工审核问题。
- `required_status` 只表达该目录项在当前目录中的提交状态，只能是“必要”“可选”“待确认”。
- `required_status` 必须由证据范围、证据强度、节点层级、父子关系和通用商务标语义类别共同判断，不得用固定标题清单或本次样本标题写死“必要”。
- `number` 是后续 Word 标题排版使用的编号前缀，优先从历史商务标投标文件学习并复用。历史中没有编号的标题必须保持 `number: null`，不要强行编号。
- 历史继承优先保留章节级、材料级目录，例如资格证明文件、商务部分摘要表、股权结构、财务报表、业绩情况表、投标保证金等可单独编排和审查的材料项。具体项目业绩清单、具体证书扫描件、协议明细、过程材料明细、逐页附件、图片说明、合同逐项列表等细碎内容，应由 opencode 判断为“素材库组装项/正文素材”，在 `outline_authoring_decisions.json` 中显式 `action: "defer"` 并写明理由，不能因为只有历史原文就默认以 `history_fallback` 全部保留进目录。

## `number` 学习规则

`number` 与 `source_text` 分离：`number` 表达 Word 排版编号，来源于历史商务标标题样式；`source_text` 表达目录项依据，优先来自当前招标文件原文。不要为了排版编号改写 `source_text`。

学习历史商务标时，应同时学习：

- 各级标题编号格式，例如一级标题 `一、`、`二、`、`三、`，二级标题 `1.1`、`2.1`、`3.1`，三级标题 `1.1.1`、`2.1.2`。
- 四级小节编号必须保留，例如 `7.2.2.1`、`7.1.2.3`；点号编号按点号数量推断层级，`7.2.2.1` 输出 `level: 4`，不得压平成 `7.2` 或 `7.2.2`。
- 历史目录中明确无编号的标题输出为 `number: null`，不要为这类标题臆造编号。
- 同级编号递增规律。只有历史样式清晰时，才可为新增同级项延续编号；无法可靠推断时用 `number: null`，必要时写入 `review_items`。

不得把招标文件附件号、表号、格式编号直接当作 Word 标题 `number`，除非历史商务标本身就是这样排版。

## `source_text` 查找顺序

`source_text` 不做孤立标题全文搜索。历史商务标目录负责决定“保留什么”；当前招标文件负责尽量提供“依据原文在哪里”。同名标题找不到，不代表当前招标文件没有依据，也不能作为删除或合并历史目录项的理由。

对每个目录项按以下顺序查找：

1. 格式章节优先：如果当前招标文件存在“投标文件格式”“响应文件格式”“商务文件格式”“格式及附件”等类似章节，优先把它当作结构化依据来源。这类章节常以正文方式先列父项，再逐个展开父项；展开处可能包含编号条目、表格字段、填表说明、普通文本列举或附件说明。
2. 父项上下文优先：先为父 section 定位格式父项或格式块；child / grandchild 必须先在父项范围内找 `source_text`。父项范围找不到时，才允许离开父范围补查。
3. 证据粒度优先：顶层 section 优先使用格式父标题；child 优先使用父范围内的编号条目、表格单元格、填写说明、后附/应附/提供/提交/复印件/证明材料等短原文。能用一句话或一个单元格，就不用整行、整段或 zone 文本。
4. 高价值区域补查：格式章节或父项上下文找不到时，再查投标文件组成/提交要求、资格要求/资格审查、符合性审查、否决条款/实质性响应、商务评分/商务评审、其他必须承诺/提交/说明区域。
5. 宽泛条款兜底：如果只有“投标人认为应当提交的其他材料”“投标文件完整性”等宽泛依据，可使用当前招标文件逐字原文作为弱 `source_text`，并将 `required_status` 设为“待确认”或说明依据较宽泛。
6. 历史商务标 fallback：只有以上都找不到时，才使用历史投标文件原文，并在 `outline_source`、`context` 或 `review_items` 中说明“历史经验保留项”。
7. 素材库组装项：不进入目录输出，不为了提供 `source_text` 而固定为 section 或 child；可在 `context` 中说明目录阶段不展开。

## 执行步骤

### 1. 定位并学习历史商务标投标文件目录

在 `bid-project-mvp` 中，历史商务标/商务模板文件由后端通过 `manifest.templateFile` 提供。必须使用该文件作为历史商务标来源，不扫描当前工作目录，不使用 `user_confirmed_inputs.json`。不要把“招标文件”误认为历史商务标投标文件。

优先使用脚本整理历史目录候选：

```bash
python scripts/prepare_history_bid_outline_inputs.py <历史商务标投标文件.docx> --output history_bid_outline_inputs.json
```

历史商务标投标文件目录识别优先级必须是：

1. Word 自动目录控件。自动目录通常是可点击“更新目录”的 Table of Contents 控件，DOCX 内部可能包含 `w:sdt`、`docPartGallery="Table of Contents"`、`TOC`、`HYPERLINK`、`PAGEREF`、`_Toc` bookmark 等字段。
2. 普通目录页。必须有明确“目录”或“目 录”标题，且后续连续多行具备目录项特征。
3. 正文明确标题结构。只有没有自动目录、没有普通目录页时，才使用正文中的 `Heading1-6`、`标题1-6` 或 `w:outlineLvl`。

如果能解析 Word 自动目录，只读取目录控件内部内容，不再从正文编号推断目录。没有自动目录时，才尝试普通目录页；普通目录页只读取“目录”标题后的连续目录块，遇到第一个正文标题或明显正文段落后停止。没有目录页时，才使用正文中的明确标题结构。

禁止仅凭正文编号模式识别目录或标题：`1.1`、`7.9.2`、`一、`、`（一）`、`附件1` 等文本编号只能在已经确认处于目录页内部时辅助判断 level，不能在正文全文中把普通段落升级为目录候选。

脚本输出包括：

- `document_name`：历史文件名。
- `blocks`：历史文件原文块。
- `outline_source`：历史目录或标题结构来源，可能包含 `source_type` 和 `history_document_name`。
- `outline_candidates`：候选目录项、`number`、层级、历史原文证据；自动目录候选可能包含 `bookmark_name` 或 `matched_body_block_id` 用于追踪。

脚本只提供候选和历史原文 fallback 证据，不直接生成 `outline.json`，不替代 AI 判断，不把历史原文默认当作最终 `source_text`。

项目集成中，`business-outline <manifest>` 会调用准备脚本，并额外生成 `document_structure_index.json` 与 `source_text_candidates.json`。该命令完成只表示候选材料准备完成，不表示商务目录生成完成；不得读取其 stdout 或 summary 当作最终结果。

### 2. 从历史商务标生成目录结构草案

基于 `history_bid_outline_inputs.json` 和对历史文件的理解，生成内部目录结构草案。

一句话原则：历史商务标目录是优先继承对象；不确定时保留，不删除。

先完整保留 `history_bid_outline_inputs.json` 中的层级关系，形成包含顶层、children、grandchildren 的内部草案；不要只学习顶层，不要把历史商务标的多级结构压平。

重点学习：

- 顶层 sections 顺序。
- 层级关系。
- 常见章节名称。
- children 归属。
- 哪些材料通常应单独编排。
- 各级标题 `number` 编号格式，以及哪些标题在历史模板中本来没有编号。

对每个历史子层级和孙层级做保留判断：历史目录项应先进入内部草案，再经过判断；删除、延后或合并历史子层级必须有强证据。

生成内部草案时，必须把每个历史候选的 `number` 继承到对应目录项。历史候选 `number` 为 `null` 时，最终目录项原则上也应为 `null`；只有确认当前新增项需要按历史同级编号规律续编时，才生成新的 `number`。

### 3. 分析当前招标文件，形成 `tender_map`

继续使用现有工具分析当前招标文件：

```bash
python scripts/prepare_tender_map_inputs.py <招标文件.docx> --expert-checklist references/expert-checklist.md --output tender_map_inputs.json
```

该脚本只提供原文块、表格结构、重点区域切片和专家清单命中候选，不替代 AI 的 `tender_map` 和目录判断。

当前招标文件重点用于识别：

- 项目名称、标段、投标人类型、联合体、保证金、报价方式等上下文。
- 投标文件组成、商务文件格式、响应文件格式、附件清单。
- 资格审查、符合性审查、废标/否决条款。
- 商务评分、类似业绩、资质、信用、承诺、声明、证明材料。
- 明确要求提交、后附、提供、填写、盖章、签署的材料。

招标文件中的规则性条款不一定直接拆成目录项。只有对应内容可单独提交、可单独编排、可单独审查，才作为新增 child 候选。

### 4. 匹配 `source_text` 并判断 `required_status`

每个最终 section 都必须尽量匹配 `source_text`。优先使用 `source_text_candidates.json` 的首选候选；当候选明显是目录页、页码、纯汇总行或错误范围时，才可改选更合适候选，并在 `reason` 中说明。

`source_text` 必须逐字复制来源原文，不得重组、改写、补全或调整编号位置。`title` 可以参考历史目录名称并做必要清理，但不得把无法证明的内容写成当前招标文件原文。

先拆开两个概念：

- `action=keep`：该目录节点暂时保留在目录树里，可能来自历史结构继承、当前招标文件宽泛覆盖、或当前阶段无法确认删除。
- `required_status=必要`：当前招标文件有足够证据证明该节点必须作为当前项目提交项。

`action=keep` 不推出 `required_status=必要`。历史项可以被保留，但如果当前招标文件证据不足，状态必须是“待确认”或在明确条件场景下为“可选”。

`required_status` 判断规则：

- “必要”：只有当前招标文件有明确提交、格式、资格、评分、组成或实质性响应证据时，才可判定。
- “可选”：仅在当前招标文件明确限定特定条件下提交时使用，例如联合体、代理商、备选方案等情形。
- “待确认”：目录项已有依据进入目录树，但当前招标文件证据不足以证明它必须作为当前项目提交项，或只存在宽泛条款、历史 fallback、父项概括证据。

证据状态矩阵：

| 证据范围/强度 | 状态判断 |
| --- | --- |
| `format_area` / `parent_context` / `high_value_area` + `strong` | 可判“必要”，但仍需确认该证据指向当前节点本身。 |
| `medium` | 父级或材料级目录可判“必要”；深层子项要谨慎，多数应为“待确认”。 |
| `full_text` / `broad_clause` / `weak` | 默认“待确认”，不能把具体历史子项批量升级为“必要”。 |
| `history_fallback` / `fallback` | 默认“待确认”，禁止判“必要”。 |
| 联合体、代理商、备选方案等明确条件项 | 判“可选”。 |

父项有强证据，不等于所有子项都“必要”。子项没有自己的当前招标文件证据时，默认“待确认”。宽泛条款只能支持 `action=keep` 或“待确认”，不能把历史具体子项批量升级成“必要”。

辅助脚本输出的 `suggested_required_status` 只是建议，不得直接当作最终判断。最终状态必须结合证据强度、证据范围、节点层级、父子关系、历史目录语义和本说明自行判定。

### 5. 保留历史子层级

对内部草案中的每个历史 child 或 grandchild，先按历史父子关系和同级关系完整放入草案，再逐项判断。不要先合并、压缩或重命名历史同级目录项。

固定顺序：

1. 先继承历史目录子层级。
2. 再尝试用当前招标文件匹配 `source_text`。
3. 匹配不到明确原文时，先判断该历史子项是章节级/材料级目录，还是具体正文素材明细。章节级/材料级目录可以使用历史投标文件 `source_text` fallback，并应 `action: "keep"` 且 `required_status: "待确认"`。
4. 匹配不到当前招标文件明确原文本身不是删除、延后或合并的强证据，不能仅因 `history_fallback`、`fallback`、`source_text` 不可信或证据不足就把历史子项批量改成 `action: "defer"`。
5. 正文素材明细必须优先显式延后为 `action: "defer"`；但 defer 的 reason 必须逐项说明该项为什么是后续正文/素材库组装、明显不适用、或已被更明确目录项覆盖，不能只写“未找到当前证据”“使用历史 fallback”，也不能对大量历史深层项复用同一句模板化理由。
6. 只有存在强证据时，才删除、延后或合并历史子项；其中“具体项目业绩清单、具体证书扫描件、协议明细、过程材料明细、逐页附件”等可视为强延后证据，但需要在 reason 中说明属于后续正文/素材库组装。
7. 如果当前招标文件对某个材料项本身有明确提交、格式、资格、评分或组成证据，且该材料可单独编排、单独审查，优先 `action: "keep"` 并按证据判断 `required_status`；不得仅因它来自历史子项就归为正文素材延后。

对 4/5 级历史深层项必须额外谨慎：

- 没有当前招标文件逐字证据时，不得判“必要”。
- 如果是正文素材明细，例如具体证书、具体项目、具体合同、过程材料、图片/附件说明，应写入 `outline_authoring_decisions.json` 且 `action: "defer"`。
- 如果暂时无法判断是不是正文素材明细，可以 `action: "keep"` 保留目录节点，但 `required_status` 只能是“待确认”。
- 父级或材料级目录已判“必要”，不自动继承给 4/5 级子项。
- `action: "defer"` 表示该项不作为最终目录节点输出，因此不能同时把 `required_status` 写成“必要”。若当前证据证明它是当前项目必须提交且可独立审查的材料项，应改为 `action: "keep"`；若它只是正文素材、附件明细或后续组装材料，则 `required_status` 应为“待确认”。

只有以下强证据存在时，才允许不继承历史 child / grandchild：

- 该项明显是后续正文组装时由素材库展开的细碎内容，例如具体项目清单、具体证书扫描件、具体协议附件、图片说明、表格行项目、设备/工厂/人员/业绩明细、逐页附件等。
- 该项明显不适用于当前项目，且有当前招标文件明确依据。
- 该项已被历史目录中另一个更明确的目录项完整覆盖。

以下情况不是延后或删除历史子层级的强证据：

- 仅未在当前招标文件找到逐字对应原文。
- 仅候选证据为 `history_fallback` / `fallback`。
- 仅认为目录太长、太细、可概括或同类项太多。
- reason 只说明“未找到当前证据”“保留历史文本作为 fallback”。这种情况下若无法证明是正文素材明细，必须 `action: "keep"` 且 `required_status: "待确认"`。
- 该项只是某个材料章节内部的具体素材明细，不具备独立目录层级价值；例如某一项目合同、某一张证书扫描件、某一份协议附件、某一过程记录或某一页图片说明。

不得因为以下原因删除或合并历史子项：

- 当前招标文件没有逐字对应 `source_text`。
- 当前招标文件只有宽泛条款覆盖。
- 多个历史子项属于同一类资格、信用、承诺、声明、否决或合规要求。
- 模型认为可以用一个概括标题表达。
- 为了让目录更短、更整齐。

对于名称较泛的父章节，例如“投标人需要说明的其他内容”“其他材料”“其他说明”“其他承诺”“其他响应”“资格/信用/符合性相关说明”“资格证明文件”“商务响应材料”等，不要因父章节名称泛化就压缩其 children。这类章节下的历史子项往往是商务标经验沉淀出的独立承诺、声明、资格状态、信用状态、合规状态、实质性响应或否决情形响应；只要它们可单独编排、可单独审查，就应直接继承为独立 children。

### 6. 用当前招标文件补强历史目录

如果当前招标文件中的要求已被历史目录明确覆盖，不重复新增。

当前招标文件用于匹配 `source_text`、发现新增必须提交材料、补强特殊要求；当前招标文件不是历史 children 保留的唯一门槛。

如果当前招标文件中的要求只是规则性条款，例如签字盖章、报价唯一、不得偏离、评分规则等，不要直接拆成目录项。

如果某项要求对应可单独提交、可单独编排、可单独审查的材料，例如承诺书、声明、证明材料、表格、截图、证书、合同、报告等，可补充为 children。

优先把补强项放入已有历史顶层 section 的 `children`。原则上不要新增顶层 section；若当前招标文件明确要求提交但历史顶层目录完全无法承载，应写入 `review_items`，不要擅自新增顶层 section。

展开组合型目录项或补强 children 时，可以使用 `extract_format_children_candidates.py`。参数必须替换为当前招标文件中真实存在的父章节和下一个同级章节。

```bash
python scripts/extract_format_children_candidates.py tender_map_inputs.json \
  --parent-source-text "<当前招标文件中真实存在的父章节原文>" \
  --next-sibling-source-text "<当前招标文件中真实存在的下一个同级章节原文>" \
  --output children_candidates.json
```

如果无法确定下一个同级章节，应先用 `get_context_block.py` 或 `tender_map_inputs.json` 复核上下文，不要凭经验猜测。也可在更可靠时使用 `--parent-title`、`--parent-section-id`、`--start-block-id`、`--end-before-block-id`。脚本只读取 `tender_map_inputs.json`，只输出候选，不直接生成 `outline.json`，不决定最终 children。`extract_format_children_candidates.py` 用于发现当前招标文件新增 children，不用于覆盖或删除历史 children。

当前招标文件新增项进入 `children` 的条件：

- 位于可靠的当前招标文件原文范围内。
- 是投标人需要单独填写、提交、后附或证明的材料单位。
- 可单独编排、可单独审查。
- 没有被现有 section 或 children 明确覆盖。
- 有当前招标文件逐字 `source_text`。

不进入 `children` 的情况：

- 只是评分规则。
- 只是签字盖章要求。
- 只是报价唯一性、不得偏离等规则性条款。
- 只是说明文字或填写提示。
- 已被更上层或更明确的目录项覆盖。

处理多标段、多报价表、多货物规格表等情况时，可依据 `tender_map` 和 `children_candidates.json` 生成或标注相应 children；不能确定时，相关 section 的 `required_status` 标为“待确认”，并视情况写入 `review_items`。

### 7. 输出 `outline.json`

先把 opencode 的语义判断写入 `outline_authoring_decisions.json`。该文件只记录每个目录项的选择和判断，不做机械拼装，不写 `children` 树。每个保留目录项必须用 `id` 或 `candidate_source_id` 指回 `source_text_candidates.json.items[*].id` 或 `history_bid_outline_inputs.json.outline_candidates[*].candidate_id`；例如 `BIZ-FALLBACK-0003` 与 `hist-cand-003` 必须能通过候选来源 ID 追踪到同一个历史候选，不能靠编号宽度猜测映射。

决策文件中的 `id` 也必须是候选 ID，例如 `BIZ-FALLBACK-0003` 或 `hist-cand-003`。不得发明 `BIZ-DECISION-0003`、`DECISION-3`、序号行 ID 或其他临时决策 ID。若需要同时保留候选项 ID 和历史来源 ID，使用 `id: "BIZ-FALLBACK-0003"` 与 `candidate_source_id: "hist-cand-003"`。

`outline_authoring_decisions.json` 最小结构：

```json
{
  "document_name": "商务标目录",
  "sections": [
    {
      "id": "BIZ-FALLBACK-0001",
      "candidate_source_id": "hist-cand-001",
      "selected_candidate_id": "cand-001",
      "required_status": "必要",
      "reason": "结合当前招标文件证据与历史目录语义保留。"
    }
  ],
  "review_items": []
}
```

写好决策文件后，必须使用固定 helper 机械写回最终 `outline.json`：

```bash
python scripts/outline_authoring_helper.py --history history_bid_outline_inputs.json --source-candidates source_text_candidates.json --decisions outline_authoring_decisions.json --output outline.json
```

`outline_authoring_helper.py` 的职责边界是读取候选、保持 ID、组装/写回 `outline.json`、运行基础校验；不得让它判断章节是否必要，不得把固定商务标题清单写入 helper。opencode 不再现场编写 Python 写回脚本。

`outline_authoring_helper.py` 不替 opencode 判断章节是否必要，但会拒绝明显违反证据状态契约的决策。例如所选候选为 `evidence_scope == "history_fallback"` 且 `evidence_strength == "fallback"` 时，`required_status` 不能是“必要”；`action: "defer"`、`omit` 或 `skip` 的节点也不能标为“必要”。遇到 helper 拒绝时，必须回到 `outline_authoring_decisions.json` 重写决策：选择当前招标文件强证据并保留为 `action: "keep"`，或把状态改为“待确认”，或将正文素材明细改为 `action: "defer"` 且不标“必要”。

helper 还会拒绝明显的批处理式延后决策：例如大量 `defer` / `omit` / `skip` 节点复用同一句模板化 reason。出现这种错误时，不要只改写措辞；必须逐项复核。能说明为正文素材、素材库组装项、明显不适用或已被覆盖的才 `defer`；不能逐项说明的历史目录项应 `action: "keep"`，并在证据不足时标为“待确认”。

如果用户要求创建文件或提供了输出目录，则最终交付名为 `outline.json` 的文件；否则只返回 `outline.json` 的 JSON 内容。

无论写入文件还是直接返回，内容都必须是一个 JSON 对象，不要添加解释、Markdown 代码块、目录说明或正文内容。

`review_items` 是 `outline.json` 的一部分，只记录最终仍需要人工确认的目录判断问题。

## `outline.json` schema

完整样例参考 `references/outline.example.json`。顶层结构：

```json
{
  "schema_version": "business_bid_outline.v1",
  "document_name": "招标文件名称",
  "outline_source": {},
  "context": {},
  "sections": [],
  "review_items": []
}
```

字段规则：

- `schema_version`：固定为 `business_bid_outline.v1`。
- `document_name`：当前招标文件名称，只写文件名或用户提供的文档名。
- `outline_source`：主目录结构学习来源。
- `context`：只记录对目录展开或后续正文生成有明显影响的关键上下文，key 使用英文 `snake_case`，每项尽量包含 `value` 或 `summary` 以及 `source_text`。
- `sections`：最终目录树，数组顺序就是商务标目录顺序。
- `review_items`：只记录目录生成完成后仍需人工审核的目录判断问题。

`outline_source` 建议字段：

- `section_title`：AI 判断出的目录结构来源说明，通常为历史商务标目录或历史商务标标题结构。
- `source_text`：用于学习顶层目录结构的历史商务标目录块或标题结构原文。
- `confidence`：只能是 `high`、`medium`、`low`。
- `source_type`：可选，建议使用 `history_bid_auto_toc`、`history_bid_toc`、`history_bid_headings`、`history_bid_unknown`、`tender_matched`、`tender_format_toc`。
- `history_document_name`：可选，历史商务标投标文件名；当目录结构来自历史文件时建议填写。

section 字段规则：

- `id`：稳定目录项 ID。项目集成场景下优先保留 `source_text_candidates.json.items[*].id`，例如 `BIZ-FALLBACK-0003`。
- `candidate_source_id`：项目集成场景下强烈要求，保留历史候选来源 ID，例如 `hist-cand-003`，用于追踪 `history_bid_outline_inputs.json`、`source_text_candidates.json` 与最终 `outline.json` 的同源关系。
- `source_candidate_item_id`：项目集成场景下强烈要求，保留 `source_text_candidates.json.items[*].id`。
- `selected_candidate_id`：项目集成场景下强烈要求，保留最终采用的 `source_text_candidates.json.items[*].candidates[*].candidate_id`。
- `title`：目录标题，可参考历史商务标目录名称。
- `number`：Word 标题排版编号，必须存在；有编号时为字符串，例如 `一、`、`1.1`、`1.1.1`；历史模板中无编号或无法可靠推断时为 `null`。
- `level`：顶层为 `1`，子项为 `2`，孙项可为 `3`；更深层级仅在历史目录确有独立目录层级且不属于素材库组装项时保留。
- `required_status`：只能是“必要”“可选”“待确认”，表示该目录项在当前目录中的提交状态。
- `source_text`：该目录项对应的逐字原文证据。优先来自当前招标文件；只有当前招标文件找不到可靠对应原文时，才可使用历史投标文件原文 fallback，并说明原因。
- `source_refs`：可选但建议保留，用于后端和前端追踪依据。
- `evidence_scope`：可选但强烈要求，记录最终选用证据的候选范围，例如 `parent_context`、`format_area`、`high_value_area`、`broad_clause`、`history_fallback`。
- `evidence_strength`：可选但强烈要求，记录最终证据强度，例如 `strong`、`medium`、`weak`、`fallback`。
- `evidence_category`：可选但强烈要求，记录最终证据类别，例如 `scoring_response`、`qualification_requirement`、`format_appendix`、`submission_requirement`。
- `reason`：可选但强烈要求，说明为何选择该 `source_text` 与 `required_status`；若为历史 fallback 必须说明原因。
- `children`：子目录项数组，没有则为空数组。

`review_items` 字段规则：

- `message`：说明目录生成中需要人工审核的问题。
- `source_text`：触发该问题的当前招标文件原文；若问题是历史 fallback 来源，也可引用对应历史原文并在 `message` 中明确说明。
- `suggested_section_id`：最可能承载该要求的 section.id；完全无法判断时为 `null`。
- `required_status`：只能是“必要”“可选”“待确认”。

## 输出与验证要求

如果用户要求创建文件或提供了输出目录，最终交付为 `outline.json` 文件；否则最终响应只输出 `outline.json` 的 JSON 内容。

生成 `outline.json` 后，建议运行 schema 校验：

```bash
python scripts/validate_outline.py outline.json
```

如果已有 `tender_map_inputs.json`，建议继续检查来自当前招标文件的 `source_text` 是否可追溯：

```bash
python scripts/check_source_text.py outline.json tender_map_inputs.json
```

若有少量 `source_text` 合理来自历史投标文件 fallback，`check_source_text.py` 可能报告 unmatched；必须在 `context` 或 `review_items` 中确认这些项已说明历史来源和原因。

还必须使用候选召回脚本复核最终目录质量：

```bash
python scripts/resolve_source_text_candidates.py tender_map_inputs.json outline.json --output source_text_candidates.json
```

检查 `source_text_candidates.json.quality_issues`，并人工复核以下情况：

- child 的 `source_text` 与父项 `source_text` 完全相同。
- 多个 sibling child 复用同一个父项标题、附件标题、表格标题或格式标题。
- `source_text` 疑似来自目录页或目次页。
- `source_text` 过长，疑似使用了整段 zone 文本。
- child / grandchild 有 `parent_context` 候选，但最终仍使用历史 fallback。

发现上述问题时，不得通过删除历史目录项来让检查通过；应优先改用当前招标文件中的父项上下文、表格行/单元格、填写说明或后附材料说明作为 `source_text`。仍无法确定时，保留目录项并标为“待确认”。

开发验收和回归测试必须运行质量门禁：

```bash
python scripts/outline_quality_gate.py --outline outline.json --tender-map tender_map_inputs.json --output-report outline_quality_report.json
```

质量门禁用于离线验收 `source_text` 可追溯性、目录页误用、历史 fallback reason、`required_status` 分布和性能，不是线上无限重试策略。门禁失败时应修复结构索引、证据召回或状态判定根因，不得通过降低阈值、删除目录节点或写死样本标题来掩盖问题。

不要输出：

- 解释文字。
- Markdown 代码块。
- 商务标正文。
- Markdown 目录。
- 额外文件清单。
- 内部 `tender_map`。

## 质量检查清单

输出前逐项自检：

1. 是否先学习历史商务标目录。
2. 是否保留历史商务标的 children 和 grandchildren，避免只学习顶层。
3. 是否先将历史目录候选纳入内部草案，再判断是否有强证据删除、延后或合并。
4. 删除、延后或合并每个历史子层级是否有强证据。
5. 是否避免因 `source_text` 匹配失败、只有宽泛条款覆盖、同类要求较多、标题可概括或目录过长而删除/合并历史子项。
6. 对“其他说明/其他材料/其他承诺/资格信用符合性说明”等泛父章节，是否保留可单独编排、可单独审查的历史 children。
7. 历史中已独立响应的资格、信用、否决、合规类承诺/声明/说明，是否没有因为其对应规则性条款而被删除或合并。
8. 每个 section 是否都有 `number` 字段。
9. 历史无编号标题是否保持 `number: null`，没有被强行编号。
10. 新增项的 `number` 是否只在历史同级编号规律清晰时续编。
11. 无法判断的历史子层级是否按历史经验项保留。
12. 是否为每个历史目录项尝试匹配当前招标文件 `source_text`。
13. 是否避免把招标文件不稳定目录块作为主目录来源。
14. 顶层 `sections` 是否保持历史目录结构。
15. 当前招标文件特殊条款、约定、必须承诺、必须提交材料是否已检查。
16. 废标、资格审查、符合性审查、商务评分线索是否都已检查。
17. 新增 children 是否可单独编排、可单独审查。
18. 规则性条款是否避免被直接拆成目录项。
19. `source_text` 是否优先来自当前招标文件。
20. 使用历史投标文件 `source_text` 的项是否已说明原因。
21. `required_status` 是否只使用“必要”“可选”“待确认”。
22. `required_status` 是否由证据强度和通用语义类别判断，而不是固定标题清单。
23. 是否保留 `evidence_scope`、`evidence_strength`、`evidence_category`、`reason`。
24. 是否没有用 `合计 | 100`、`总计 | ...`、`小计 | ...` 等汇总行替代强标题或段落候选。
25. 是否已通过 `scripts/validate_outline.py`。
26. 如果已有 `tender_map_inputs.json`，是否已用 `scripts/check_source_text.py` 检查当前招标文件来源的 `source_text` 可追溯。
27. 是否已运行 `scripts/outline_quality_gate.py`，并确认质量门禁通过。
28. 是否没有把 `history_fallback` + `fallback` 的目录项判为“必要”。
29. 4/5 级历史深层项没有当前招标文件逐字证据时，是否为“待确认”或 `action: "defer"`。
30. 父项强证据是否没有被无条件传播给所有子项。
31. 是否没有仅因找不到当前招标文件原文或只有历史 fallback，就把历史子层级批量改成 `action: "defer"`。
32. 若有多个 `action: "defer"`，reason 是否逐项说明了正文素材/素材库组装、不适用或被覆盖依据，而不是复用同一句模板化理由。
