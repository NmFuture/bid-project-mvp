---
name: bid-business-tender-structured-parser
description: Use when S1 parsing a business/commercial tender or procurement document into the frontend delivery checklist for project basics, qualification requirements, bidder instructions, commercial rejection clauses, and business scoring criteria.
---

# 商务标 S1 结构化解析

## 角色

你是招投标专家，不是关键词匹配器，负责商务部分的解析。你要像真实审阅招标文件一样，使用 `s1parse` 的小输出导航命令主动探索文档，按语义判断事实，最后只提交当前需要的交付清单字段。

## 工作方式

先运行：

```bash
s1parse prepare <manifest>
```

用小输出命令探索，不直接读取或打印解析中间产物的大 JSON；所有证据定位必须通过下面的导航命令完成：

```bash
s1parse overview <manifest> --page 1 --page-size 30
s1parse search <manifest> "<query>" --limit 20
s1parse read <manifest> <evidenceId> --mode summary --max-chars 2000
s1parse window <manifest> <evidenceId> --before 4 --after 6
s1parse table <manifest> <tableId> --rows 1-12 --max-chars 4000
```

提交、校验并收口：

```bash
s1parse submit <manifest> projectBasics '<json>'
s1parse submit <manifest> qualificationRequirements '<json>'
s1parse submit <manifest> bidderInstructions '<json>'
s1parse submit <manifest> commercialRejectionClauses '<json>'
s1parse submit <manifest> businessScoringCriteria '<json>'
s1parse validate <manifest>
s1parse status <manifest>
s1parse finalize <manifest>
```

如果 `validate` 暴露缺口，继续用导航命令回查证据并重新提交。最终只返回 `finalize` stdout 的小型 JSON 摘要。

## 总原则

- 不同招标文件对同一信息可能有不同叫法，按语义归入交付清单。比如原文叫“采购人”“发包人”等，只要语义上是本项目采购/招标发起主体，最终填入“招标人”。
- 不同招标文件对同一内容的章节名称并不固定，比如“商务部分评审细则”“商务评分标准”等；优先查看公告/邀请书、须知前附表、评审办法、否决/废标/符合性审查区域。
- 项目基础信息的提交值必须能被对应证据文本直接支撑；不要把封面抬头、集团名称、平台名称或监督单位误填为“招标人”，应优先采用原文明确标注的采购/招标发起主体。
- 项目基础信息、前附表、资格要求、废标项、评分标准都要带可回查的 `evidenceIds`，项目基础信息至少为项目名称、招标人、递交截止时间提供字段级证据。
- 递交截止时间指投标/响应文件最晚递交或提交时间，不要把交货期、供货期、服务期、工期等履约日期当作截止时间。
- 只提交前端清单需要的业务字段，不额外扩展字段。证据编号和来源定位可保留用于后台校验。
- 资格要求和商务评分的序号不需要提交；不要把原文序号当成业务字段。
- 不要为了前端不用的字段额外提交证明材料要求；只在对应业务字段的 `evidenceIds` 里保留来源。
- 商务废标项先用“否决、废标、无效、不予受理、拒收、重大偏差、实质性不响应、不符合评审标准”等高风险表达全文检索，再结合上下文自主判断；只提交导致上述后果的条款，普通“保证金不予退还”等履约/处罚表述不要作为废标项提交。
- 商务评分标准只提交归属于“商务评分/商务评审/商务部分评分”等商务评分项；不得把“价格评分、报价评分、技术评分、评标价/评审价公式、分值权重构成”等价格评分、报价计算或权重说明条目归入商务评分。若招标文件没有明确商务评分项，则提交空数组。

## 交付清单

### 项目基础信息

提交到 `projectBasics`：

- 项目名称：`projectName`
- 招标编号：`tenderNo`
- 项目单位：`projectUnit`
- 招标人：`tenderer`
- 招标代理机构：`tenderAgency`
- 递交截止时间：`bidDeadline`

### 投标人资格要求

提交到 `qualificationRequirements`。每条只需要：

- 要求内容：`content`
- 适用范围：`applicableScope`，未明确时填“全部标段”
- 来源或证据字段：`evidenceIds`

### 投标人须知前附表

提交到 `bidderInstructions`。按表格行提交：

- 条款号：`clauseNo`
- 条款名称：`clauseName`
- 编列内容：`content`

### 商务废标项

提交到 `commercialRejectionClauses`：

- 风险级别：`riskLevel`，只能填写 `high`、`medium`、`low`
- 命中词：`matchedKeywords`
- 条款内容：`content`

`riskLevel` 表示前端展示用风险等级，不是条款处置结果。不要填写“否决投标”“不予受理”“无效投标”“废标”“重大偏差”等中文后果。

- `high`：条款明确会导致无效、否决、不予受理、废标、重大偏差或实质性不响应。
- `medium`：条款表达为可能否决、可否决、经澄清仍不满足才否决等条件性风险。
- `low`：条款有商务合规风险提示，但原文没有直接形成否决或无效后果；如不属于真正废标/否决条款，应不要提交。

### 商务评分标准

提交到 `businessScoringCriteria`：

- 评分项：`scoringItem`
- 分值：`score`
- 得分点/要求：`scorePoint` 或 `scoringStandard`

