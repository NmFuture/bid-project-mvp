---
name: bid-business-wiki-material-builder
description: 当需要从原始素材清单重建商务标素材 Wiki 时使用，用于缺口处理、表格填写、证据选取或标书组装
allowed-tools: [Read, Glob, Grep, Bash, Write, AskUserQuestion]
---

# 商务标素材 Wiki 构建器

## 概述

构建最小够用的商务标 Wiki，让下游 Agent 能够了解：

- 存在哪些商务素材
- 它们能支撑哪些模板模块
- 素材应该整件附加、作为图片证据使用，还是仅用于填充字段/表格
- 哪些变量仍需人工确认
- 哪些证据存在有效期或版本风险

将 Wiki 视为面向 AI 的检索与合规索引，而非散文式知识库。

## 工作方式：脚本产骨架 + LLM 精修

这是一个「确定性脚本 + AI 精修」的 skill，两层各司其职：

1. **脚本产骨架（确定性、不可省略）**
   调用 `scripts/run_from_manifest.py`，由 `business_wiki_blueprint.py` 从 `materialInventory.items` 生成**稳定的 Wiki 骨架**：固定五个一级节点、13 个模板模块映射、每条素材一张证据卡片，以及从路径/标题/标签/OCR 文本里用规则抽取的初始字段（业务分类、usage_mode、有效期猜测、风险提示等）。
   这一步保证：节点结构稳定、素材不遗漏不重复、绝不编造金额/承诺/证书编号。

2. **LLM 精修（你来做，在骨架之上）**
   读脚本产出的 `wiki_blueprint.json`，在**不破坏结构、不编造事实**的前提下做语义层面的增强：
   - 修正脚本规则误判的 `business_category` / `evidence_topic` / `usage_mode`
   - 补全脚本留空或标 `待识别`/`待映射` 的语义字段（关键词、适用章节、摘要）
   - 复核脚本标记 `needs_human_confirm=yes`、`validity_status=pending_verify` 的项，必要时改写 `risk_notes` 让人工复核更聚焦
   - 当映射表 `candidate_card_ids` 为空但你判断有合适素材时，按 `fallback_scope` 给出更精准的候选建议

**铁律**：精修只能改"判断/描述"，不能改"事实"。脚本从未在 inventory 里出现过的价格、日期、证书编号、授权人、业绩数据，LLM 一律不得新增——找不到就保持 `pending` 并写进待确认清单。

### 调用脚本

```bash
python scripts/run_from_manifest.py <manifest.json>
```

manifest 至少包含 `materialInventory`（含 `items`）、可选 `rootTitle` / `workDir` / `outputFile`。脚本把完整骨架写入 `outputFile`（默认 `<workDir>/wiki_blueprint.json`），并在 stdout 返回一个精简回执：

```json
{
  "schema_version": "bid-wiki-blueprint-v1",
  "skill": "bid-business-wiki-material-builder",
  "outputFile": "...",
  "summary": "...",
  "rootTitle": "商务标Wiki（自动生成）",
  "materialCount": 0,
  "nodeTitles": ["01-素材总表", "02-模板模块映射表", "03-证据卡片", "04-待填写与待确认清单", "05-使用规则"]
}
```

精修后，把结果写回同一个 blueprint JSON（schema 见下）。

## 使用场景

用于商务标 Wiki 的创建，或在原始素材变更后进行重建。

典型下游场景：

- S3 缺口处理
- 为资格证明和业绩附件选取证据
- 填写报价/规格/偏差表
- 组装商务标投标文件包

不适用于纯技术标素材、技术方案撰写，或编造不存在的商务事实。

## 输入契约（materialInventory.items）

每条素材是一个对象，关键字段：

- `id`（**必填、全局唯一**）：证据卡片的 `card_id` 以此为种子（`biz-card-<id>`）。缺失时脚本会退回用文件名 stem，**不同目录下的同名文件会撞 card_id**，导致映射歧义。后端构建 inventory 时必须为每条注入唯一 id。
- `path` / `folderPath` + `name`：原始素材库相对路径，决定身份层级（通用/客户/项目）与分组。
- `tags`：原始标签，**必须保留**——下游素材匹配靠标签缩小检索范围。
- `identityScope` / `materialTier`：身份范围（general/customer/project）。
- 清洗元数据：`cleanStatus`、`cleanResultStatus`、`cleanMessage`、`cleanedFileName`、`sourceMinioKey`、`cleanedMinioKey`、`cleanRelativeSourcePath`、`cleanRelativeOutputPath`、`cleanNeedsHumanReview`、`cleanUsableForRetrieval`。
- AI 身份字段：`customerId`/`customerName`、`projectId`/`projectCode`，用于区分通用/客户/项目素材。
- 可选内容字段：`headings`、`paragraphs`、`tables`、`keywords`、`businessWikiOcr`（OCR 文本与字段）。

## 输出契约

最终 Wiki 是一个 JSON（不要用 Markdown 代码块包裹），schema：

```json
{
  "summary": "简短的结果摘要",
  "rootTitle": "商务标Wiki（自动生成）",
  "nodes": [
    {
      "title": "节点标题",
      "markdownContent": "# 节点标题\n\n内容",
      "tags": ["商务标"],
      "applicableTypes": ["商务标"],
      "children": []
    }
  ]
}
```

根节点必须包含以下五个一级工作节点，按此顺序排列：

1. `01-素材总表`
2. `02-模板模块映射表`
3. `03-证据卡片`
4. `04-待填写与待确认清单`
5. `05-使用规则`

仅允许在这五个节点下嵌套额外的子节点。

如果没有商务素材，仍然输出同样的五个节点，作为待补料框架。

## 核心模式

从 `materialInventory.items` 生成。

对于每一条真实的商务素材：

- 在 `01-素材总表` 中包含一次
- 在 `03-证据卡片` 下创建或引用一张证据卡片
- 保留其来源路径和清洗后的文件名（如存在）
- 保留原始素材的 `tags`，因为下游素材匹配依赖标签来缩小检索范围
- 保留清洗元数据，如 `cleanStatus`、`cleanResultStatus`、`cleanMessage`、源对象 key、清洗后对象 key 以及审查标记
- 保留 AI 身份字段，以便后续 Agent 能正确区分通用素材、客户素材和项目素材
- 为其指定推荐的商务类别和模块使用方式

## 各节点职责

### 01-素材总表

创建一张紧凑的表格供快速浏览。

必须包含：文件名、来源层级、身份范围、商务类别、推荐模块、原始标签、清洗状态、清洗策略、证据类型、原始路径。

### 02-模板模块映射表

此节点回答：

- 对于给定的商务模板模块，应首先搜索哪些路径范围
- 哪些证据卡片是当前最佳候选
- 素材是用于整件附加、字段提取、图片提取、表格填写还是仅供参考

**模板模块固定为以下 13 个**（与脚本 `MODULE_CONFIGS` 一一对应，编号即节点序号）：

| module_code | module_name | 默认 usage_mode |
| --- | --- | --- |
| BM-01 | 01-商务评分索引表 | reference_only |
| BM-02 | 02-投标函与授权模块 | extract_fields |
| BM-03 | 03-投标价格表模块 | fill_table |
| BM-04 | 04-货物规格一览表模块 | fill_table |
| BM-05 | 05-商务偏差表模块 | fill_table |
| BM-06 | 06-投标保证金模块 | attach_whole |
| BM-07 | 07-履约保证承诺模块 | attach_whole |
| BM-08 | 08-资格证明文件模块（附件7） | attach_whole |
| BM-09 | 09-业绩情况表模块（附件7I） | fill_table |
| BM-10 | 10-开标价格表模块 | fill_table |
| BM-11 | 11-其他说明与承诺模块（附件9） | attach_whole |
| BM-12 | 12-否决项与符合性响应模块 | extract_fields |
| BM-13 | 13-供应链协同模块 | reference_only |

每行应包含以下等效字段：

- `module_name`
- `module_code`
- `source_path_prefix`
- `business_category`
- `candidate_card_ids`
- `usage_mode`
- `mapping_source`
- `confidence`
- `needs_human_confirm`
- `mapping_reason`
- `fallback_scope`
- `missing_hint`

### 03-证据卡片

创建按需加载的证据卡片，尽可能与原始资料库的结构对应：

- `通用素材`
- `客户素材/{客户名称}`
- `项目素材/{项目代号}`

然后按二级商务文件夹分组。

卡片是索引记录，而非完整文档。

每张卡片应覆盖以下字段组：

- 基本身份与路径字段
- AI 身份字段
- 来源字段：原始 MinIO key、清洗后 MinIO key、清洗后文件名，以及可用时的清洗报告状态
- 模块决策字段
- 内容摘要与关键词
- 有效期字段，如可检测到的签发日期和到期日期
- 风险字段，如 OCR 不确定性、版本不确定性和人工确认需求

图片证书或扫描证据应保持原始优先。不要强制将其纳入清洗后的 Word 使用语义。

### 04-待填写与待确认清单

列出在最终组装前必须解决的项目时空白项或待决策项。

包含高频商务项目，例如：

- 项目名称 / 项目编号 / 客户名称
- 授权代表
- 投标报价
- 开标价格
- 投标保证金金额
- 有效期
- 证据包选择
- 证书有效性检查
- 偏差/合规确认
- 附件页码索引检查

不要在 Wiki 内部填写具体值。仅指向候选来源并标记阻塞级别。

### 05-使用规则

说明下游 Agent 应如何使用商务 Wiki：

- 首先按身份过滤
- 在全文搜索之前先查阅模块映射表
- 优先级：项目素材 > 客户素材 > 通用素材
- 对于 `fill_table` 模块，提取字段而非附加整份源文件
- 对于图片/扫描件，保留原件并在需要时要求人工验证
- 如果映射遗漏了已有素材，回退到当前可读身份范围内的限定搜索
- 绝不编造价格、日期、承诺、证书编号或业绩事实

## 字段可信度说明（精修时务必牢记）

脚本里的以下字段是**正则启发式猜测**，命中率随证书/文档版式波动，属于"提示性"而非"权威"信息——真值依赖人工审核环节（需求中的"素材和填写审核"）：

- `issue_date` / `expiry_date` / `validity_status`（来自 `DATE_RE` 等正则）
- `document_number`（来自 `DOC_NO_RE`）
- `issuer`（来自 `ISSUER_RE`）

脚本对这些字段已做保守兜底：识别不确定时置 `validity_status=pending_verify`，并把 `needs_human_confirm` 设为 `yes`、写入 `risk_notes`。**LLM 精修时不要把"提示值"当成"已核实事实"对外承诺**，也不要因为想让卡片"看起来完整"而填入未经核实的日期或编号。

## 质量规则

- 不得编造报价、金额、证书编号、授权人、日期、业绩事实或合同承诺。
- 保持 Wiki 精简，面向检索。
- 如果文件没有标题，仍需创建卡片并标记风险。
- 如果证书或截图的时效信息不明确，标记为 `pending_verify`。
- 如果映射表不完整，依靠 `fallback_scope` 加限定范围全文搜索，而非凭空编造。
