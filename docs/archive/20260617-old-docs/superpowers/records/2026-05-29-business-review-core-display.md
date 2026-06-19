# 商务解析页核心信息展示交付记录

记录日期：2026-05-29

## 背景

商务解析链路已经能产出 `parseData.structured`，后端和 Skill 当前稳定提供以下结构：

- `structured.fieldGroups.projectBasics`
- `structured.fieldGroups.qualificationRequirements`
- `structured.fieldGroups.bidderInstructions`
- `structured.fieldGroups.commercialRejectionClauses`
- `structured.scoringCriteria.business`
- `structured.scoringCriteria.price`
- `structured.scoringCriteria.compliance`

本次前端目标不是重新解析，而是在商务解析完成后按固定模型集中展示核心商务决策信息，避免主区域继续呈现散乱字段。

## 本次收口内容

### 前端展示

主要文件：`code/sewpg-bid-frontend/src/workspaces/business/pages/BusinessTenderReview.jsx`

- 新增固定展示配置：
  - `PROJECT_BASIC_FIELDS`
  - `CORE_REVIEW_SECTIONS`
  - `SCORING_SECTION_TITLES`
- 新增专用轻量表格：
  - `ProjectBasicsTable`
  - `QualificationRequirementsTable`
  - `BidderInstructionsTable`
  - `CommercialRejectionClausesTable`
- 保留 `ScoringCriteriaTable`，继续展示 `business`、`price`、`compliance` 三类评分标准。
- 主视图顺序收口为：
  1. 项目基础信息
  2. 投标人资格要求
  3. 投标人须知前附表
  4. 商务废标项
  5. 商务评分细则
  6. 投标报价评分标准
  7. 符合性审查标准
  8. 商务文档预览
- `projectBasics` 只按固定顺序展示：
  - 项目名称
  - 招标编号
  - 招标人
  - 招标代理机构
  - 递交截止时间
- 缺失核心值显示为“未识别”。
- 空数据时显示友好空态：
  - “未识别到投标人资格要求。”
  - “未识别到投标人须知前附表。”
  - “未识别到商务废标项。”
- 商务废标项风险级别：
  - `high` 使用错误色/红色强调。
  - `medium` 使用普通提示色。

辅助样式文件：`code/sewpg-bid-frontend/src/index.css`

- 新增 `.business-core-text-cell`，让核心表格长文本可换行，移动端通过横向滚动避免文字重叠。

### 后端与 Skill 契约

相关文件：

- `code/sewpg-bid-backend/app/services/parsing.py`
- `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/SKILL.md`
- `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_contract.py`

本次契约补齐围绕商务解析页需要的字段模型：

- `projectBasics` 收口到 `projectName`、`tenderNo`、`tenderer`、`tenderAgency`、`bidDeadline`。
- 新增资格要求、投标人须知前附表、商务废标项的结构化输出。
- 保留既有 `businessResponse`、`qualificationSupport`、`commitmentRequirements` 等字段，但前端主视图不突出展示这些散乱项。
- 评分标准继续沿用 `structured.scoringCriteria.business`、`price`、`compliance`。

### 测试覆盖

相关测试：

- `code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`
- `code/sewpg-bid-backend/tests/test_parse_pipeline.py`
- `code/sewpg-bid-backend/tests/test_s1parse_container_integration.py`
- `code/sewpg-bid-backend/tests/test_s1parse_router_script.py`

测试补齐重点：

- Skill 脚本输出包含新增 `fieldGroups`。
- S1 router 和后端兜底解析路径包含新增核心结构。
- `business`、`price`、`compliance` 三类评分不回退。
- DOCX 样本能解析出前附表、代理机构、截止时间和废标风险条款。

## 样本验收结果

真实样本验收数据来自本地 `解析增强/current_sample_structured_result.after.json`，页面人工核对到以下结果：

- 项目名称：华能赤峰市翁牛特旗等6个风电项目共计1998MW风力发电机组及其附属设备集中采购预招标
- 招标编号：HNZB2025-12-1-382
- 招标人：中国华能集团有限公司
- 招标代理机构：中国华能集团有限公司北京睿采数动科技分公司
- 递交截止时间：2026-01-26
- 资格要求：12 条
- 投标人须知前附表：44 行
- 商务废标项：15 条
- 商务评分标准：11 条

## 验证命令

前端验证：

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-frontend
npm install
npm run lint
npm run build
```

后端相关验证：

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m pytest tests/test_business_parse_skill_script.py tests/test_parse_pipeline.py tests/test_s1parse_router_script.py -q
```

Docker 重建与健康检查：

```powershell
cd C:\Users\99065\Documents\商务标V2\code
docker compose -p bid_pwf up -d --build --force-recreate
docker compose -p bid_pwf ps
```

已确认 `web`、`fastapi`、`worker`、`opencode`、`postgres`、`redis`、`minio`、`onlyoffice` 启动，API 健康检查 `/api/healthz` 返回 `ok`。

## 提交边界

建议纳入提交：

- 商务解析核心字段展示前端改动。
- 后端和 Skill 的商务核心字段契约补齐。
- 对应测试文件。
- `code/AGENT.md` 中协作边界与提交规则补充。
- 本交付记录。

不建议纳入本次提交：

- `解析增强/`：真实样本和解析产物，体量大，且包含标书样本。
- `模版提取切片/`：模板提取原型和输出产物。
- `s1_commitment_letters/`：承诺函样例产物。
- `doc_pwf/`：本地文档样例。
- `docs/superpowers/plans/` 下尚未确认归档的既有计划文件。

## 后续注意

- 前端主视图继续以固定商务核心模型为准，不把 `businessResponse`、`qualificationSupport`、`commitmentRequirements`、`commitmentClues` 和大量证据明细直接铺到主区域。
- 如果后续需要展示证据明细，应放在折叠区或详情态，不改变主视图的决策信息顺序。
- 后续若调整 `fieldGroups` 契约，需要同步更新前端专用表格和后端/Skill 测试。
