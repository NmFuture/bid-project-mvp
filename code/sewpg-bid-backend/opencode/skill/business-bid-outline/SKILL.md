---
name: business-bid-outline
description: 当用户要求生成商务标目录、商务标大纲、商务响应目录、投标文件目录结构或 outline.json 时使用。先学习历史商务标投标文件目录结构，再用当前招标文件要求匹配 source_text 并补强特殊提交材料，最终只输出 outline.json。
---

# Business Bid Outline

## Project Integration Contract

When this skill is executed inside `bid-project-mvp`, the required entrypoint is:

```bash
business-outline <manifest>
```

The backend provides the uploaded historical business bid/template file through `manifest.templateFile`. Use that file as the historical business bid source. Do not scan the current working directory for a historical bid file, and do not use `user_confirmed_inputs.json`.

The native skill artifact remains `outline.json` with `schema_version: "business_bid_outline.v1"` and top-level `sections[]`. The `business-outline <manifest>` runner only prepares input JSON files. For frontend compatibility, the backend converts final `outline.json.sections[]` into `manifest.outputFile` (`bid-toc-json-v1`) after the skill has completed.

Required project artifacts in `manifest.workDir`:

- `history_bid_outline_inputs.json`
- `tender_map_inputs.json`
- `outline.json`

For `outline.json.sections[]`, preserve enough evidence for backend conversion: at least `title`, `level`, `required_status`, `source_text`, and optional `source_refs`. `source_refs[]` should include tender refs with `type: "tender"`, `role: "basis"`, and searchable text in `searchText`/`basisText`/`rawText` so the current frontend can show basis cards and jump in OnlyOffice after backend conversion.

你是资深标书专家。你的任务是生成商务标目录结构文件 `outline.json`：先学习历史商务标投标文件的目录结构、层级和顺序，再用当前招标文件中的特殊条款、约定、必须承诺项、必须提交材料、废标/资格/符合性/商务评分要求补强目录。

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

- 生成商务标正文
- 生成 Markdown 目录
- 自动生成完整投标文件
- 输出 `outline.json` 以外的最终交付物
- 把当前招标文件中的“投标文件格式”“响应文件格式”等不稳定目录块作为顶层 `sections` 的主来源
- 无条件把历史投标文件原文作为最终 `source_text`

## 工作原则

- 历史商务标投标文件是历史经验的结晶，是目录结构的优先继承对象：顶层、children、grandchildren 都要学习并尽量保留，用于保留顺序、层级关系、常见章节名称、children / grandchildren 归属和哪些材料通常单独编排。
- 历史 child / grandchild 默认应保留；只有存在强证据表明该项不适合目录阶段保留时，才允许删除、延后或合并。
- 不得仅因为当前招标文件没有逐字对应 `source_text`、只有宽泛条款覆盖、多个历史子项同属一类要求、标题可被概括表达或为了让目录更短更整齐，就删除或合并历史 section、child 或 grandchild。
- 当前招标文件 `source_text` 匹配失败，只影响 `source_text` 的选择和 `required_status` 判断，不构成删除历史子项的理由。
- 只有能明确判断为“素材库组装项”、明显不适用于当前项目且有当前招标文件明确依据、或已被另一个更明确历史目录项完整覆盖的历史子层级，才在目录生成阶段延后、不保留或合并。
- 无法判断某个历史子层级是否应删除时，优先按“历史经验项”保留，并用 `required_status`、`context` 或 `review_items` 标明当前招标文件证据不足。
- 当前招标文件是当前项目要求的权威来源，也是 `source_text` 的优先来源。
- 从历史目录学习来的每个 section、child 或 grandchild，都必须尽量回到当前招标文件中寻找对应原文。
- 找不到当前招标文件明确原文不代表删除；历史经验项可使用历史投标文件原文作为 `source_text` fallback。
- 当前项目补强项的 `source_text` 必须来自当前招标文件，不能来自历史投标文件。
- 顶层 `sections` 原则上保持历史商务标目录结构，不为匹配当前招标文件不稳定目录块而重排。
- `review_items` 只记录完成目录判断后仍影响目录项存在、归属或状态的人工审核问题。
- `required_status` 只表达该目录项在当前目录中的提交状态，只能为“必要”“可选”“待确认”。
- `number` 是后续 Word 标题排版使用的编号前缀，优先从历史商务标投标文件学习并复用；历史中没有编号的标题必须保持 `number: null`，不要强行编号。

### number 学习规则

`number` 与 `source_text` 分离：`number` 表达 Word 排版编号，来源于历史商务标标题样式；`source_text` 表达目录项依据，优先来自当前招标文件原文。不要为了排版编号改写 `source_text`。

学习历史商务标时，应同时学习：

- 各级标题编号样式，例如一级标题 `一、`、`二、`、`三、`，二级标题 `1.1`、`2.1`、`3.1`，三级标题 `1.1.1`、`2.1.2`。
- 历史目录中明确无编号的标题，例如“商务评分索引表”“供货保障专题”，输出为 `number: null`。
- 同级编号递增规律。只有历史样式清晰时，才可为新增同级项延续编号；无法可靠推断时用 `number: null`，必要时写入 `review_items`。

不得把招标文件附件号、表号、格式编号直接当作 Word 标题 `number`，除非历史商务标就是这样排版。

### source_text 结构化查找顺序

`source_text` 不做孤立标题全文搜索。历史商务标目录负责决定“保留什么”；当前招标文件负责尽量提供“依据原文在哪里”。同名标题找不到，不代表当前招标文件没有依据，也不能作为删除、合并历史目录项的理由。

对每个目录项按以下顺序查找：

1. 格式章节优先：如果当前招标文件存在“投标文件格式、响应文件格式、商务文件格式、格式及附件”等类似章节，优先把它当成结构化依据来源。这类章节常以正文方式先列父项，再逐个展开父项；展开处可能包含编号条目、表格字段、填表说明、普通文本列举或附件说明。
2. 父项上下文优先：先为父 section 定位格式父项或格式块；child / grandchild 必须先在父项范围内找 `source_text`。父项范围找不到时，才允许离开父范围补查。
3. 证据粒度优先：顶层 section 优先使用格式父标题；child 优先使用父范围内的编号条目、表格单元格、填写说明、后附/应附/提供/提交/复印件/证明材料等短原文。能用一句话或一个单元格，不用整行、整段或 zone 文本。
4. 高价值区域补查：格式章节或父项上下文找不到时，再查投标文件组成/提交要求、资格要求/资格审查、符合性审查/否决条款/实质性响应、商务评分/商务评审、其他必须承诺/提交/说明区域。
5. 宽泛条款兜底：如果只有“投标人认为应当提交的其他材料”“投标文件完整性”等宽泛依据，可以使用当前招标文件逐字原文作为弱 `source_text`，并将 `required_status` 设为“待确认”或说明依据较宽泛。
6. 历史商务标 fallback：只有以上都找不到时，才使用历史投标文件原文，并在 `outline_source`、`context` 或 `review_items` 中说明“历史经验保留项”。
7. 素材库组装项：不进入目录输出，不为了提供 `source_text` 而固定为 section 或 child；可在 `context` 中说明目录阶段不展开。

## 执行步骤

### 1. 定位并学习历史商务标投标文件目录

在 `bid-project-mvp` 中，历史商务标/商务模板文件由后端通过 `manifest.templateFile` 提供。必须使用该文件作为历史商务标来源，不扫描当前工作目录，不使用 `user_confirmed_inputs.json`。不要把“招标文件”误认为历史商务标投标文件。

优先使用 `scripts/prepare_history_bid_outline_inputs.py` 整理历史目录候选：

```bash
python scripts/prepare_history_bid_outline_inputs.py <历史商务标投标文件.docx> --output history_bid_outline_inputs.json
```

历史商务标投标文件目录识别优先级必须是：

1. Word 自动目录控件。自动目录通常是可点击“更新目录”的 Table of Contents 控件，DOCX 内部可能包含 `w:sdt`、`docPartGallery="Table of Contents"`、`TOC`、`HYPERLINK`、`PAGEREF`、`_Toc` bookmark 等字段。
2. 普通目录页。必须有明确“目录”或“目 录”标题，且后续连续多行具备目录项特征。
3. 正文明确标题结构。只有没有自动目录、没有普通目录页时，才使用正文中的 `Heading1-6`、`标题1-6` 或 `w:outlineLvl`。

如果能解析 Word 自动目录，只读取目录控件内部内容，不要再从正文编号推断目录。没有自动目录时，才尝试普通目录页；普通目录页只读取“目录”标题后的连续目录块，遇到第一个正文标题或明显正文段落后停止。没有目录页时，才使用正文中的明确标题结构。

禁止仅凭正文编号模式识别目录或标题：`1.1`、`7.9.2`、`一、`、`（一）`、`附件1` 等文本编号只能在已经确认处于目录页内部时辅助判断 level，不能在正文全文中把普通段落升级为目录候选。

该脚本负责读取历史商务标 DOCX，输出：

- `document_name`：历史文件名。
- `blocks`：历史文件原文块。
- `outline_source`：历史目录或标题结构来源，可能包含 `source_type` 和 `history_document_name`。
- `outline_candidates`：候选目录项、`number`、层级、历史原文证据；自动目录候选可能包含 `bookmark_name` 或 `matched_body_block_id` 用于追溯。

脚本只提供候选和历史原文 fallback 证据，不直接生成 `outline.json`，不替代 AI 判断，不把历史原文默认当作最终 `source_text`。

### 2. 从历史商务标生成目录结构草案

基于 `history_bid_outline_inputs.json` 和 AI 对历史文件的理解，生成内部目录结构草案。

一句话原则：历史商务标目录是优先继承对象；不确定时保留，不删除。

先完整保留 `history_bid_outline_inputs.json` 中的层级关系，形成包含顶层、children、grandchildren 的内部草案；不要只学习顶层，不要把历史商务标的多级结构压平。

重点学习：

- 顶层 sections 顺序。
- 层级关系。
- 常见章节名称。
- children 归属。
- 哪些材料通常应单独编排。
- 各级标题 `number` 编号样式，以及哪些标题在历史模板中本来没有编号。

对每个历史子层级和孙层级做保留判断：历史目录项应先进入内部草案，再经过判别；删除、延后或合并历史子层级必须有强证据。

不要为了匹配当前招标文件中的“投标文件格式”“响应文件格式”等不稳定目录块而重排历史目录结构。

生成内部草案时，必须把每个历史候选的 `number` 继承到对应目录项。历史候选 `number` 为 `null` 时，最终目录项原则上也应为 `null`；只有确认当前新增项需要按历史同级编号规律续编时，才生成新的 `number`。

### 3. 分析当前招标文件，形成 tender_map

继续使用 `scripts/prepare_tender_map_inputs.py`、`references/expert-checklist.md`、`scripts/get_context_block.py` 等现有工具分析当前招标文件。

```bash
python scripts/prepare_tender_map_inputs.py <招标文件.docx> --expert-checklist references/expert-checklist.md --output tender_map_inputs.json
```

该脚本只提供原文块、表格结构、重点区域切片和专家清单命中候选，不替代 AI 的 `tender_map` 和目录判断。

当前招标文件重点用于识别：

- 项目名称、标段、投标人类型、联合体、保证金、有效期等上下文。
- 特殊条款、特殊约定。
- 必须承诺项、必须响应项、必须提交材料。
- 表格中隐藏的提交要求。
- 废标条款。
- 资格审查要求。
- 符合性审查要求。
- 商务评分相关证明材料。
- 与历史目录草案中每个目录项对应的当前招标文件原文证据。

第 3 步不要把所有发现写入 `review_items`。只有后续步骤完成目录判断后仍无法确定的问题，才进入最终 `outline.json.review_items`。

#### 专家清单与参考样例

- `references/expert-checklist.md` 是可持续补充的专家经验清单，用于指导重点区域识别，不是硬编码目录规则。
- `references/outline.example.json` 是 `outline.json` 输出格式样例，可用于理解 schema，但不要照抄示例内容。

### 4. 为历史目录草案匹配当前招标文件 source_text

对每个从历史目录学习来的 section、child 或 grandchild：

1. 先按“格式章节优先、父项上下文优先、证据粒度优先、高价值区域补查、宽泛条款兜底、历史 fallback 最后”的顺序查找 `source_text`。
2. 匹配时先去除历史目录编号，弱化附件号、表号、格式编号差异，提取核心标题词；不要要求历史标题与当前招标文件逐字同名。
3. 父项找到格式父项或格式块后，child 和 grandchild 优先在该范围内匹配编号条目、表格字段、填表说明、普通文本列举、附件说明或材料提交语句。
4. 选择候选时先看结构身份，再看文本相似度：顶层 section 优先格式父标题；child 优先父范围内短原文；评分、资格、符合性、宽泛条款只能作为补充，不应压过格式章节中的父项/子项依据。
5. 若找到明确当前招标文件原文，使用当前招标文件逐字原文作为 `source_text`。
6. 若只能找到宽泛对应原文，使用该宽泛原文作为 `source_text`，并将该项 `required_status` 设为“待确认”或在 `review_items` 中提示人工确认。
7. 若完全找不到可靠当前招标文件原文，不删除该历史目录项；后续按“历史子层级保留规则”决定保留、延后或不输出。

复核上下文时优先使用：

```bash
python scripts/get_context_block.py tender_map_inputs.json --text <关键词或原文> --format md
```

对未匹配或疑似历史 fallback 的项，先使用候选召回脚本二次补查：

```bash
python scripts/resolve_source_text_candidates.py tender_map_inputs.json outline.json --output source_text_candidates.json
```

该脚本只召回候选，不自动替换 `source_text`，不替 AI 做最终判断。生成最终 `outline.json` 时必须消费 `source_text_candidates.json`：

- 对 unmatched、疑似历史 fallback、child 使用父项标题作为 `source_text`、多个 sibling 复用同一 `source_text` 的项，必须先查看该项候选。
- child / grandchild 有父项时，优先选择 `scope` 为 `parent_context` 的候选；其次是 `format_area`，再其次是 `high_value_area`、`broad_clause`，最后才允许历史 fallback。
- 父项为摘要表、信息表、资格表、格式表、材料清单、承诺书、声明函等表单/格式类章节时，child 不得直接使用父项标题；优先使用父项范围内的编号条目、表格单元格、填写说明、后附/应附/须附/提供/提交/复印件/证明材料等短原文。若同一位置同时有表格整行和单元格/短句，优先单元格/短句。
- zone 只能用于定位上下文，不能直接作为最终 `source_text`。目录页、目次页、末尾页码型文本也不能作为最终 `source_text`。
- 候选必须逐字复制当前招标文件原文。候选能弱支撑但不够精确时，保留历史目录项并将 `required_status` 设为“待确认”或写入 `review_items`，不要为了消除 unmatched 而强行把父项标题塞给 child。
- 如果存在 `parent_context` 候选却仍使用历史 fallback，必须在 `review_items` 中说明为什么父项上下文不能支撑该项。

选择候选时仍需根据上下文判断它是否能支撑该目录项；如果候选只是宽泛依据，按“待确认”处理。

`source_text` 必须逐字复制来源原文，不得重组、改写、补全或调整编号位置。`title` 可以参考历史目录名称并做必要清理，但不得把无法证明的内容写成当前招标文件原文。

### 5. 历史子层级保留规则

对内部草案中的每个历史 child 或 grandchild，先按历史父子关系和同级关系完整放入草案，再逐项判断。不要先合并、压缩或重命名历史同级目录项。

执行顺序固定为：

1. 先继承历史目录子层级。
2. 再尝试用当前招标文件匹配 `source_text`。
3. 匹配不到明确原文时，可以使用历史投标文件 `source_text` fallback。
4. 只有存在强证据时，才删除、延后或合并历史子项。

历史商务标中的 child / grandchild 默认应保留。只有以下强证据存在时，才允许不继承：

- 该项明显是后续正文组装时由素材库展开的细碎内容，例如具体项目清单、具体证书扫描件、具体协议附件、图片说明、表格行项目、设备/工厂/人员/业绩明细、逐页附件等。
- 该项明显不适用于当前项目，且有当前招标文件明确依据。
- 该项已被历史目录中另一个更明确的目录项完整覆盖。

不得因为以下原因删除或合并历史子项：

- 当前招标文件没有逐字对应 `source_text`。
- 当前招标文件只有宽泛条款覆盖。
- 多个历史子项属于同一类资格、信用、承诺、声明、否决或合规要求。
- 模型认为可以用一个概括标题表达。
- 为了让目录更短、更整齐。

当前招标文件 `source_text` 匹配失败，只影响 `source_text` 的选择和 `required_status` 判断，不构成删除历史子项的理由。如果没有强证据，保留历史子项。

对于名称较泛的父章节，例如“投标人需要说明的其他内容”“其他材料”“其他说明”“其他承诺”“其他响应”“资格/信用/符合性相关说明”“资格证明文件”“商务响应材料”等，不要因为父章节名称泛化就压缩其 children。这类章节下的历史子项往往是商务标经验沉淀出来的独立承诺、声明、资格状态、信用状态、合规状态、实质性响应或否决情形响应；只要它们可单独编排、可单独审查，就应直接继承为独立 children。

招标文件中的资格、信用、否决、合规要求本身通常是规则性条款，不一定直接拆成目录。但如果历史商务标已经把这些要求响应成独立承诺、声明或说明类目录项，这些历史目录项应作为历史经验继承，不能因为它们对应的是规则性要求就删除或合并。

一句话原则：历史商务标目录是优先继承对象；不确定时保留，不删除。

### 6. 用当前招标文件补强历史目录

如果当前招标文件中的要求已经被历史目录明确覆盖，不重复新增。

当前招标文件用于匹配 `source_text`、发现新增必须提交材料、补强特殊要求；当前招标文件不是历史 children 保留的唯一门槛。

如果当前招标文件中的要求只是规则性条款，例如签字盖章、报价唯一、不得偏离、评分规则等，不要直接拆成目录项。

如果某项要求对应可单独提交、可单独编排、可单独审查的材料，例如承诺书、声明、证明材料、表格、截图、证书、合同、报告等，可以补充为 children。

优先把补强项放入已有历史顶层 section 的 `children`。原则上不要新增顶层 section；若当前招标文件明确要求提交但历史顶层目录完全无法承载，应写入 `review_items`，不要擅自新增顶层 section。

展开组合型目录项或补强 children 时，可以使用 `extract_format_children_candidates.py`。使用时必须把参数替换为当前招标文件中真实存在的父章节和下一个同级章节。

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

处理多标段、多报价表、多货物规格表等情况时，可依据 `tender_map` 和 `children_candidates.json` 生成或标记相应 children；不能确定时，相关 section 的 `required_status` 标为“待确认”，并视情况写入 `review_items`。

### 7. 输出 outline.json

如果用户要求创建文件或提供了输出目录，则写入名为 `outline.json` 的文件；否则只返回 `outline.json` 的 JSON 内容。

无论写入文件还是直接返回，内容都必须是一个 JSON 对象，不要添加解释、Markdown 代码块、目录说明或正文内容。

`review_items` 是 `outline.json` 的一部分，只记录最终仍需要人工确认的目录判断问题。

## outline.json schema

参考完整样例见 `references/outline.example.json`。顶层结构：

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

字段说明：

- `schema_version`：固定为 `business_bid_outline.v1`。
- `document_name`：当前招标文件名称，只写文件名或用户提供的文档名。
- `outline_source`：主目录结构学习来源。
  - `section_title`：AI 判断出的目录结构来源说明，通常为历史商务标目录或历史商务标标题结构。
  - `source_text`：用于学习顶层目录结构的历史商务标目录块或标题结构原文。
  - `confidence`：只能是 `high` / `medium` / `low`。
  - `source_type`：可选，建议使用 `history_bid_auto_toc`、`history_bid_toc`、`history_bid_headings`、`history_bid_unknown`、`tender_matched`、`tender_format_toc`。
  - `history_document_name`：可选，历史商务标投标文件名；当目录结构来自历史文件时建议填写。
- `context`：只记录对目录展开或后续正文生成有明显影响的关键上下文，key 使用英文 snake_case，每项尽量包含 `value` 或 `summary` 以及 `source_text`。
- `sections`：最终目录树，数组顺序就是商务标目录顺序。
- `review_items`：只记录目录生成完成后仍需人工审核的目录判断问题。

section 字段规则：

- `id`：稳定目录项 ID，建议 `sec-001`、`sec-001-001`。
- `title`：目录标题，可参考历史商务标目录名称。
- `number`：Word 标题排版编号，必须存在；有编号时为字符串，例如 `一、`、`1.1`、`1.1.1`；历史模板中无编号或无法可靠推断时为 `null`。
- `level`：顶层为 `1`，子项为 `2`，孙项可为 `3`；更深层级仅在历史目录确有独立目录层级且不属于素材库组装项时保留。
- `required_status`：只能是“必要”“可选”“待确认”，表示该目录项在当前目录中的提交状态。
  - “必要”：当前招标文件明确要求提交，或历史目录项已被当前招标文件明确/宽泛要求证明应纳入。
  - “可选”：仅在特定条件下提交，例如联合体、代理商、备选方案等情形。
  - “待确认”：该目录项已有依据进入目录树，但是否适用、是否保留或是否独立列出仍需人工判断。
- `source_text`：该目录项对应的逐字原文证据。优先来自当前招标文件；只有当前招标文件找不到可靠对应原文时，才可使用历史投标文件原文 fallback，并说明原因。
- `children`：子目录项数组，没有则为空数组。

review_items 字段规则：

- `message`：说明目录生成中需要人工审核的问题。
- `source_text`：触发该问题的当前招标文件原文；若问题是历史 fallback 来源，也可引用对应历史原文并在 `message` 中明确说明。
- `suggested_section_id`：最可能承载该要求的 section.id；完全无法判断时为 `null`。
- `required_status`：只能是“必要”“可选”“待确认”。

## 输出要求

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
- `source_text` 疑似来自目录页/目次页。
- `source_text` 过长，疑似使用了整段 zone 文本。
- child / grandchild 有 `parent_context` 候选，但最终仍使用历史 fallback。

发现上述问题时，不得通过删除历史目录项来让检查通过；应优先改用当前招标文件中的父项上下文、表格行/单元格、填写说明或后附材料说明作为 `source_text`。仍无法确定时，保留目录项并标为“待确认”。

不要输出：

- 解释文字
- Markdown 代码块
- 商务标正文
- Markdown 目录
- 额外文件清单
- 内部 `tender_map`

## 质量检查清单

输出前逐项自检：

1. 是否先学习历史商务标目录？
2. 是否保留了历史商务标的 children 和 grandchildren，避免只学习顶层？
3. 是否先将历史目录候选纳入内部草案，再判断是否有强证据删除、延后或合并？
4. 删除、延后或合并每个历史子层级是否有强证据？
5. 是否避免因 `source_text` 匹配失败、只有宽泛条款覆盖、同类要求较多、标题可概括或目录过长而删除/合并历史子项？
6. 对“其他说明/其他材料/其他承诺/资格信用符合性说明”等泛父章节，是否保留可单独编排、可单独审查的历史 children？
7. 历史中已独立响应的资格、信用、否决、合规类承诺/声明/说明，是否没有因为其对应规则性条款而被删除或合并？
8. 每个 section 是否都有 `number` 字段？
9. 历史无编号标题是否保持 `number: null`，没有被强行编号？
10. 新增项的 `number` 是否只在历史同级编号规律清晰时续编？
11. 无法判断的历史子层级是否按历史经验项保留？
12. 是否为每个历史目录项尝试匹配当前招标文件 `source_text`？
13. 是否避免把招标文件不稳定目录块作为主目录来源？
14. 顶层 `sections` 是否保持历史目录结构？
15. 当前招标文件特殊条款、约定、必须承诺、必须提交材料是否已检查？
16. 废标、资格审查、符合性审查、商务评分线索是否都已检查？
17. 新增 children 是否可单独编排、可单独审查？
18. 规则性条款是否避免被直接拆成目录项？
19. `source_text` 是否优先来自当前招标文件？
20. 使用历史投标文件 `source_text` 的项是否已说明原因？
21. `required_status` 是否只使用“必要”“可选”“待确认”？
22. 是否已通过 `scripts/validate_outline.py`？
23. 如果已有 `tender_map_inputs.json`，是否已用 `scripts/check_source_text.py` 检查当前招标文件来源的 `source_text` 可追溯？
