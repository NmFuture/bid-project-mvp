# 商务标解析结果 Contract 设计

> 用途：冻结商务标专用解析模块的结果结构，作为后续 skill、后端、前端实现的唯一对齐依据。  
> 状态：步骤一产出稿，待审核。  
> 更新日期：2026-05-07

## 1. 文档目标

本文件只解决三件事：

1. 商务标解析结果最终要输出什么结构。
2. 与当前技术标解析结果相比，哪些字段保留、删除、替换。
3. 商务标新增的承诺函与附表产物，元数据结构到底长什么样。

一句话原则：

> 商务标解析结果不是“技术标解析结果删几项”这么简单，而是一份面向商务响应、资格支撑、报价/偏差/承诺模块消费的独立 contract。

## 2. 设计边界

### 2.1 本 contract 约束的范围

1. 后端 `parse_results` 返回 JSON 结构。
2. opencode 商务标解析 skill 输出 JSON 结构。
3. 本地 fallback 解析输出 JSON 结构。
4. 前端商务标解析页展示所依赖的数据结构。

### 2.2 本 contract 暂不约束的范围

1. 承诺函最终法律措辞模板。
2. 商务标后续自动生成链路如何消费这些结果。
3. 解析产物是否自动进入原始素材库或 Wiki。

## 3. 当前技术标解析结构回顾

当前技术标解析的主结构大致为：

```json
{
  "status": "completed",
  "summary": {},
  "items": [],
  "structured": {
    "sourceDocuments": [],
    "scoringCriteria": {
      "technical": [],
      "business": [],
      "price": [],
      "lcoe": [],
      "compliance": []
    },
    "fieldGroups": {
      "projectBasics": [],
      "turbineCoreParameters": [],
      "performanceGuarantees": [],
      "environmentAdaptation": [],
      "scoringCriteria": []
    },
    "requirementPresence": {
      "topicPlans": {},
      "supplyScope": {},
      "assessmentTerms": {}
    },
    "coverage": [],
    "projectDates": {
      "startDate": "",
      "endDate": ""
    },
    "appendices": []
  }
}
```

当前技术标解析页也按这个结构渲染：

1. 评分标准表
2. 项目基础信息
3. 风机核心参数
4. 性能保证指标
5. 环境适应性
6. 专题方案 / 供货范围 / 考核条款
7. 附表空表产物
8. 证据明细

这套结构不适合直接承接商务标。

## 4. 商务标解析 contract 的设计原则

商务标解析 contract 设计遵循六条原则：

1. 保留外层基础骨架，降低接入成本。
2. 重新定义 `structured` 内部业务语义。
3. 删除技术标专属字段组，不在商务标中伪保留空壳。
4. 新增“承诺函派生产物”作为一级明确对象。
5. 保持每个识别结果都能回溯 `sourceFile / sourceDocumentId / evidence / evidenceLocation`。
6. 让前端可以按“商务评分 / 商务响应 / 资格支撑 / 承诺函 / 附表”自然展示。

## 5. 商务标解析结果总结构

建议商务标解析结果采用以下总结构：

```json
{
  "status": "completed",
  "summary": {
    "fileCount": 0,
    "extractedCount": 0,
    "textLength": 0,
    "textPreview": "",
    "warnings": [],
    "targetSkill": "bid-business-tender-structured-parser",
    "categoryCounts": {},
    "projectDates": {
      "startDate": "",
      "endDate": ""
    },
    "appendixCount": 0,
    "commitmentLetterCount": 0
  },
  "items": [],
  "structured": {
    "schemaVersion": "bid-business-tender-structured-v1",
    "targetSkill": "bid-business-tender-structured-parser",
    "mode": "opencode-skill | local-structured-parser",
    "sourceDocuments": [],
    "scoringCriteria": {
      "business": [],
      "price": [],
      "compliance": []
    },
    "fieldGroups": {
      "projectBasics": [],
      "businessResponse": [],
      "qualificationSupport": [],
      "commitmentRequirements": []
    },
    "requirementPresence": {
      "qualificationDocuments": {},
      "performanceDocuments": {},
      "deviationResponse": {},
      "bidSecurity": {},
      "otherCommitments": {},
      "disqualificationClauses": {}
    },
    "coverage": [],
    "projectDates": {
      "startDate": "",
      "endDate": ""
    },
    "appendices": [],
    "commitmentLetters": []
  }
}
```

## 6. 外层字段定义

### 6.1 顶层保留字段

| 字段 | 是否保留 | 说明 |
|---|---|---|
| `status` | 保留 | 保持与当前解析接口一致 |
| `summary` | 保留并扩展 | 新增 `commitmentLetterCount` |
| `items` | 保留 | 作为证据明细平铺索引，前端仍可直接展示 |
| `structured` | 保留 | 但内部结构改为商务标语义 |

### 6.2 顶层 `summary` 新增字段

建议在现有基础上新增：

| 字段 | 说明 |
|---|---|
| `commitmentLetterCount` | 生成的承诺函数量 |

## 7. `structured` 内部字段设计

### 7.1 基础控制字段

| 字段 | 说明 |
|---|---|
| `schemaVersion` | 固定为 `bid-business-tender-structured-v1` |
| `targetSkill` | 固定为商务标解析 skill 名 |
| `mode` | `opencode-skill` 或 `local-structured-parser` |

### 7.2 `sourceDocuments`

用途：

记录参与解析的源文件清单，基本沿用当前结构。

建议字段：

```json
{
  "id": "DOC-1",
  "name": "商务招标文件.docx",
  "role": "evaluation | commercial_volume | qualification_volume | unknown",
  "sourcePath": "",
  "textPath": "",
  "textLength": 0,
  "pageCount": 0,
  "warnings": []
}
```

说明：

1. `role` 不再强调 `technical_spec`。
2. 商务标更常见的角色建议是：
   - `evaluation`
   - `commercial_volume`
   - `qualification_volume`
   - `unknown`

## 8. `scoringCriteria` 设计

### 8.1 保留哪些评分桶

商务标仅保留：

1. `business`
2. `price`
3. `compliance`

明确删除：

1. `technical`
2. `lcoe`

### 8.2 评分行字段

建议沿用当前行结构，避免前端和后续消费成本过高：

```json
{
  "id": "SCORE-0001",
  "order": 1,
  "scoringItem": "企业业绩",
  "score": "10分",
  "scorePoint": "近三年类似项目供货业绩",
  "proofRequirement": "提供合同、中标通知书、验收证明",
  "sourceFile": "评标办法.docx",
  "sourceDocumentId": "DOC-1",
  "section": "附表3：商务评分标准表",
  "evidence": "企业业绩10分……",
  "evidenceLocation": "P12"
}
```

说明：

1. 当前技术标评分行已有 `sourceFile / evidence / evidenceLocation`。
2. 商务标建议补齐并固定保留 `sourceDocumentId / section`。

## 9. `fieldGroups` 设计

商务标字段组建议只保留四组：

1. `projectBasics`
2. `businessResponse`
3. `qualificationSupport`
4. `commitmentRequirements`

明确删除：

1. `turbineCoreParameters`
2. `performanceGuarantees`
3. `environmentAdaptation`
4. 技术标 fallback 中平铺型 `scoringCriteria` 字段组

### 9.1 通用字段对象结构

建议字段组中的每个字段对象统一为：

```json
{
  "key": "projectName",
  "label": "项目名称",
  "value": "华能某项目",
  "status": "found | missing | derived | pending_confirm",
  "sourceFile": "商务招标文件.docx",
  "sourceDocumentId": "DOC-1",
  "section": "第一章 投标人须知",
  "evidence": "项目名称：华能某项目",
  "evidenceLocation": "P2",
  "confidence": 0.98
}
```

相比当前技术标字段对象，建议新增固定字段：

1. `sourceDocumentId`
2. `section`
3. `confidence`

### 9.2 `projectBasics`

保留共用项目基础字段：

1. `projectName`
2. `tenderNo`
3. `tenderer`
4. `managementUnit`
5. `bidSectionScale`
6. `deliveryPeriod`
7. `warrantyPeriod`

删除：

1. `technicalCommitment`

原因：

商务标里不应再把“技术承诺”当作基础字段。

### 9.3 `businessResponse`

这是商务标新增的核心字段组，建议至少包括：

1. `bidLetterRequired`
2. `authorizationLetterRequired`
3. `integrityCommitmentRequired`
4. `sealValidityStatementRequired`
5. `bidPriceTableRequired`
6. `openingPriceTableRequired`
7. `specificationTableRequired`
8. `commercialDeviationTableRequired`
9. `supplyScopeTableRequired`
10. `bidSecurityRequired`
11. `performanceBondCommitmentRequired`
12. `attachment9Required`

这些字段的值不一定是最终内容，更多是：

1. 识别是否要求
2. 提取要求摘要
3. 记录来源位置

### 9.4 `qualificationSupport`

用于识别商务标要求中的资格与业绩支撑材料，建议字段包括：

1. `qualificationDocumentRequired`
2. `performanceDocumentRequired`
3. `financialDocumentRequired`
4. `creditDocumentRequired`
5. `certificationDocumentRequired`
6. `customerSpecificProofRequired`

### 9.5 `commitmentRequirements`

这是商务标新字段组，专门承接承诺函生成前的识别结果。

建议字段包括：

1. `generalCommitmentCount`
2. `disqualificationCommitmentRequired`
3. `otherCommitmentSectionRequired`
4. `commitmentGenerationBasis`

说明：

1. 这个字段组不是承诺函结果本身。
2. 它只是“承诺函为什么会生成、生成了多少”的识别层。

## 10. `requirementPresence` 设计

当前技术标 `requirementPresence` 是：

1. `topicPlans`
2. `supplyScope`
3. `assessmentTerms`

商务标建议替换为：

1. `qualificationDocuments`
2. `performanceDocuments`
3. `deviationResponse`
4. `bidSecurity`
5. `otherCommitments`
6. `disqualificationClauses`

每个对象建议结构：

```json
{
  "status": "present | missing | partial",
  "summary": "已识别到资格证明文件要求……",
  "evidences": [
    {
      "sourceFile": "商务招标文件.docx",
      "sourceDocumentId": "DOC-1",
      "section": "附件7",
      "evidence": "投标人证明其是合格投标人……",
      "evidenceLocation": "P25"
    }
  ]
}
```

## 11. `coverage` 设计

`coverage` 建议保留，但商务标语义重定义为“商务模块覆盖情况”。

建议覆盖维度：

1. 商务评分要求
2. 报价与价格表
3. 偏差响应
4. 资格证明
5. 业绩证明
6. 保证金
7. 其他承诺

当前步骤一只冻结字段存在，不先冻结复杂算法。

## 12. `projectDates` 设计

保留当前结构：

```json
{
  "startDate": "",
  "endDate": ""
}
```

解析口径继续沿用：

1. 只记录招标/报名/投标/开标阶段日期
2. 不记录供货期、服务期、履约期等执行日期

## 13. `appendices` 设计

### 13.1 定位

商务标中的 `appendices` 仍表示：

> 从招标文件解析出来、需要生成空表或标准附件底稿、且可预览的派生产物

它不承接承诺函。

### 13.2 建议字段结构

在当前技术标附表字段基础上，建议冻结为：

```json
{
  "id": "APPX-0001",
  "artifactType": "appendix",
  "title": "附件7：资格证明文件清单",
  "status": "generated | pending | failed",
  "sourceFile": "商务招标文件.docx",
  "sourceDocumentId": "DOC-1",
  "section": "附件7",
  "evidence": "附件7：资格证明文件",
  "evidenceLocation": "P25",
  "rows": [],
  "rowCount": 0,
  "docxPath": "/abs/path.docx",
  "workspacePath": "s1_appendices/APPX-0001-附件7.docx",
  "availableParseFields": [],
  "notes": "",
  "previewType": "onlyoffice"
}
```

### 13.3 与当前技术标附表相比新增字段

建议新增：

1. `artifactType`
2. `sourceDocumentId`
3. `section`
4. `availableParseFields`
5. `notes`
6. `previewType`

## 14. `commitmentLetters` 设计

### 14.1 定位

`commitmentLetters` 是商务标新增的核心对象，表示：

> 根据招标文件“承诺”要求或“投标人不得存在下列情形之一”条款，自动派生出的承诺函 Word 产物

### 14.2 建议字段结构

```json
{
  "id": "CL-0001",
  "artifactType": "commitment_letter",
  "title": "投标人不存在下列情形之一承诺函",
  "commitmentType": "disqualification | general_commitment | compliance_commitment",
  "status": "generated | pending_review | failed",
  "sourceFile": "商务招标文件.docx",
  "sourceDocumentId": "DOC-1",
  "section": "投标人须知",
  "triggerText": "投标人不得存在下列情形之一",
  "triggerContext": "……上下文摘要……",
  "evidence": "投标人不得存在下列情形之一……",
  "evidenceLocation": "P18",
  "docxPath": "/abs/path.docx",
  "workspacePath": "s1_appendices/CL-0001-投标人不存在下列情形之一承诺函.docx",
  "placementHint": "投标人需要说明的其他内容",
  "needsHumanReview": true,
  "riskFlags": [
    "template_generated",
    "legal_wording_review_required"
  ],
  "previewType": "onlyoffice"
}
```

### 14.3 字段说明

| 字段 | 作用 |
|---|---|
| `artifactType` | 固定为 `commitment_letter` |
| `commitmentType` | 承诺函类型 |
| `triggerText` | 直接触发生成的关键词或句子 |
| `triggerContext` | 触发位置上下文摘要 |
| `placementHint` | 明确后续应放入“投标人需要说明的其他内容” |
| `needsHumanReview` | 明确承诺函需要人工复核 |
| `riskFlags` | 标记法律措辞、聚类、重复等风险 |

### 14.4 最低强制规则

1. 只要命中“投标人不得存在下列情形之一”，必须生成一份固定承诺函。
2. 普通“承诺”命中结果允许经过聚类、去重后生成多份。
3. 同一类承诺不应无限重复生成。

## 15. `items` 平铺证据清单口径

顶层 `items` 建议保留，原因：

1. 便于前端继续展示“证据明细”
2. 便于后续做统一检索、导出、调试
3. 降低对现有接口兼容改造成本

但商务标 `items.category` 应改为商务语义分类，建议包括：

1. `business_scoring`
2. `price_scoring`
3. `compliance_scoring`
4. `project_basics`
5. `business_response`
6. `qualification_support`
7. `commitment_requirement`
8. `appendix_requirement`
9. `disqualification_clause`

## 16. 前端展示分块建议

商务标解析页建议分为以下 7 个区块：

1. 商务评分标准
   - `structured.scoringCriteria.business / price / compliance`
2. 项目基础信息
   - `fieldGroups.projectBasics`
3. 商务响应识别
   - `fieldGroups.businessResponse`
4. 资格与业绩支撑要求
   - `fieldGroups.qualificationSupport`
5. 承诺函识别与生成结果
   - `fieldGroups.commitmentRequirements`
   - `structured.commitmentLetters`
6. 商务附表/附件产物
   - `structured.appendices`
7. 证据明细
   - 顶层 `items`

当前技术标页面应删除的板块：

1. 风机核心参数
2. 性能保证指标
3. 环境适应性
4. 专题方案 / 供货范围 / 考核条款

## 17. 与当前技术标 contract 的映射关系

| 当前技术标字段 | 商务标处理方式 |
|---|---|
| `scoringCriteria.technical` | 删除 |
| `scoringCriteria.business` | 保留 |
| `scoringCriteria.price` | 保留 |
| `scoringCriteria.lcoe` | 删除 |
| `scoringCriteria.compliance` | 保留 |
| `fieldGroups.projectBasics` | 保留并裁剪 |
| `fieldGroups.turbineCoreParameters` | 删除 |
| `fieldGroups.performanceGuarantees` | 删除 |
| `fieldGroups.environmentAdaptation` | 删除 |
| `requirementPresence.topicPlans` | 替换 |
| `requirementPresence.supplyScope` | 替换 |
| `requirementPresence.assessmentTerms` | 替换 |
| `appendices` | 保留并扩展 |
| `commitmentLetters` | 新增 |

## 18. 本步骤的冻结结论

步骤一建议冻结如下结论：

1. 商务标解析必须采用独立 schema：
   - `bid-business-tender-structured-v1`
2. 商务标解析结果保留外层骨架：
   - `status / summary / items / structured`
3. `structured` 内部改为商务标专用字段组。
4. `appendices` 保留，但只表示商务附表/附件空表产物。
5. `commitmentLetters` 新增，专门承接承诺函派生产物。
6. 前端商务标解析页必须按本 contract 重新分块展示。

## 19. 下一步建议

下一步即可进入执行计划中的步骤二：

1. 在后端解析服务中加入 `bidType=商务标` 分流；
2. 让商务标解析走新的 schemaVersion、skillName、prompt builder；
3. 为步骤三的新 skill 建好骨架。
