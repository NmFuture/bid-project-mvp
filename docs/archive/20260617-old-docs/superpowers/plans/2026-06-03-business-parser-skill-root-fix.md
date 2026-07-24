# 商务招标结构化解析 Skill 根因改造实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `bid-business-tender-structured-parser` 的 `finalize` 结果在真实商务招标文件上稳定通过最终验真，避免后端旧兜底覆盖 skill 结果，并修复项目基础信息、资格要求、商务废标项、商务评分边界和前端展示契约问题。

**Architecture:** 先把“证据可追溯”提升为 skill 的一等契约，确保候选包、表格行、最终记录使用同一套 evidence id registry。然后让后端只在 skill 未产出可用结果时使用旧兜底，不再用旧逻辑覆盖已完成 finalize 的 skill 结果。最后在 skill 内部用条款号、表格区段和文档层级做领域边界，不再依赖任意关键词行匹配。

**Tech Stack:** Python skill scripts, backend pytest, React 前端页面测试或组件级断言。

---

## 根因原则

本次不能通过以下方式解决：

- 不降低 `validate_final_result()` 的严格度。
- 不删除 `evidence_references` 检查。
- 不把 `workflow.stage` 强行改成 `finalized`。
- 不针对“闻喜、太谷、寿阳、武乡”文件写特例。
- 不靠前端隐藏错误结果来掩盖后端覆盖问题。

正确方向是让 skill 产出的每一条最终记录都有可回溯证据，并让后端尊重 skill 的结构化契约。

## 文件职责

- `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_workflow.py`
  - 负责候选包、AI review、finalize、最终验真。
  - 本次改造证据注册、表格行证据、评分行级边界、资格和废标合成。
- `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_contract.py`
  - 负责基础商务字段、投标人须知前附表、旧结构兼容输出。
  - 本次改造项目基础信息匹配规则，尤其是 `tenderer` 和 `bidDeadline`。
- `code/sewpg-bid-backend/app/services/parsing.py`
  - 负责后端调用 skill、finalize guard、旧兜底 `_transform_to_business_contract()`。
  - 本次改造兜底策略，避免旧逻辑覆盖已 finalize 的 skill 结果。
- `code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`
  - 增加 skill 脚本级回归测试。
- `code/sewpg-bid-backend/tests/test_parse_pipeline.py`
  - 增加后端管线级回归测试，断言不会触发 `backendFallbackTransformApplied`。
- `code/sewpg-bid-frontend/src/workspaces/business/pages/BusinessTenderReview.jsx`
  - 同步新评分契约，只展示实际存在的商务评分分组。

---

## Task 1: 建立统一证据注册表，修复最终验真失败的根因

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_workflow.py`
- Test: `code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`

- [ ] **Step 1: 写失败测试，复现表格行证据无法回溯**

新增一个测试，构造包含 `投标人须知前附表` 和 `评标办法前附表` 的最小 DOCX，执行 `prepare` + 决策 + `finalize`，断言：

```python
self.assertEqual(validation_report["status"], "passed")
self.assertEqual(structured["workflow"]["validationStatus"], "passed")
self.assertEqual(structured["workflow"]["stage"], "finalized")
self.assertFalse(any(
    check["name"] == "evidence_references" and check["status"] == "failed"
    for check in validation_report["checks"]
))
```

运行：

```bash
cd code/sewpg-bid-backend
pytest tests/test_business_parse_skill_script.py::BusinessParseSkillScriptTests::test_business_finalize_registers_table_row_evidence -q
```

期望：当前失败，失败原因是 `evidence_references`。

- [ ] **Step 2: 在候选包构建阶段注册表格行 evidence**

在 `business_workflow.py` 中把表格行证据纳入 `candidate_package.evidenceIndex`。每个表格行生成稳定 id：

```text
{sourceDocumentId}:{tableId}/R{one_based_row_number}
```

并保证表格行对象、由表格行派生的候选、最终记录都使用同一个 `evidenceIds`。

- [ ] **Step 3: 去掉“最终阶段再临时拼 evidence id”的隐式依赖**

保留 `_record_evidence_ids()` 作为兼容入口，但最终记录优先继承候选或表格行上的 `evidenceIds`。`evidenceLocation` 只作为展示字段，不再作为唯一证据来源。

- [ ] **Step 4: 验证所有最终记录都能回 evidenceIndex**

新增测试辅助断言：

```python
for record in final_records:
    if record.get("evidence"):
        self.assertTrue(
            any(eid in evidence_index for eid in record.get("evidenceIds", [])),
            record,
        )
```

运行：

```bash
pytest tests/test_business_parse_skill_script.py -q
```

---

## Task 2: 改造后端兜底策略，避免旧逻辑覆盖 skill finalize 结果

**Files:**
- Modify: `code/sewpg-bid-backend/app/services/parsing.py`
- Test: `code/sewpg-bid-backend/tests/test_parse_pipeline.py`

- [ ] **Step 1: 写失败测试，断言已完成 skill workflow 不被旧兜底覆盖**

构造 skill 返回：

```json
{
  "structured": {
    "mode": "opencode-skill",
    "workflow": {
      "stage": "fallback",
      "validationStatus": "failed"
    },
    "fieldGroups": {
      "qualificationRequirements": [{"content": "资格要求样例", "evidenceIds": ["TEN-1:L1"]}]
    }
  }
}
```

断言后端不调用 `_transform_to_business_contract()` 覆盖该结果，而是保留 skill 结构和 workflow 诊断。

- [ ] **Step 2: 明确 fallback 分层**

后端只在以下情况调用旧 `_transform_to_business_contract()`：

- skill 未运行。
- skill 输出不是 business structured payload。
- skill manifest 不存在 review plan，说明没有进入新版 workflow。

后端不得在以下情况覆盖 skill 结果：

- `structured.targetSkill == "bid-business-tender-structured-parser"`。
- workflow 已包含 `candidatePackagePath`、`reviewPlanPath`、`validationReportPath`。
- opencode 已完成 `finalize`，即使 `validationStatus = failed`。

- [ ] **Step 3: 对验证失败结果只加诊断，不二次重算**

保留：

```json
"workflow": {
  "stage": "fallback",
  "validationStatus": "failed",
  "backendFinalizeGuardApplied": true
}
```

但不写入：

```json
"backendFallbackTransformApplied": true
```

除非旧兜底确实作为唯一解析来源运行。

---

## Task 3: 用条款号和字段语义修复项目基础信息识别

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_contract.py`
- Test: `code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`

- [ ] **Step 1: 写投标人须知前附表字段测试**

测试输入包含：

- `1.1.2 招标人 名称：山西漳山发电有限责任公司 ...`
- `3.2.5 投标报价的其他要求 招标人不接受投标人任何形式的价格调整声明...`

断言：

```python
self.assertEqual(field_by_key(project_basics, "tenderer")["value"], "山西漳山发电有限责任公司")
self.assertIn("1.1.2", field_by_key(project_basics, "tenderer")["evidence"])
```

- [ ] **Step 2: 为 `tenderer` 使用前附表条款优先级**

匹配顺序：

1. `clauseNo == "1.1.2"` 且 `clauseName` 为 `招标人`。
2. 招标公告正文中的 `招标人为...`。
3. 封面 `招标人：...`。

禁止把仅在内容中出现“招标人”的普通条款作为 `tenderer`。

- [ ] **Step 3: 为 `bidDeadline` 增加排除规则和强匹配规则**

强匹配：

- `clauseName` 等于 `投标截止时间`、`投标文件递交截止时间`、`递交截止时间`。
- 或正文明确为 `递交截止时间：YYYY年MM月DD日 HH时MM分`。

排除：

- `投标截止时间10日前`
- `收到澄清后12小时内`
- `收到修改后12小时内`
- `开标结束后10分钟内`

最终 `bidDeadline` 必须带 `sourceFile`、`section`、`evidenceLocation`、`evidenceIds`。

---

## Task 4: 资格要求保持 AI review 结果，不再因旧兜底丢失

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_workflow.py`
- Test: `code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`

- [ ] **Step 1: 写资格候选回归测试**

构造 6 个 `qualification_review` task，每个 task 至少接受一条候选。断言 `finalize` 后：

```python
self.assertGreaterEqual(len(field_groups["qualificationRequirements"]), 6)
self.assertTrue(all(row.get("evidenceIds") for row in field_groups["qualificationRequirements"]))
self.assertEqual(workflow["validationStatus"], "passed")
```

- [ ] **Step 2: 确认资格最终记录只从 accepted candidates 合成**

`_qualification_rows_from_accepted_candidates()` 应作为资格最终合成的唯一入口。不要再从旧 keyword line scan 回填资格要求。

---

## Task 5: 商务废标项改为“标题命中后展开下级条款”

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_workflow.py`
- Test: `code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`

- [ ] **Step 1: 写 `1.4.3` 展开测试**

输入：

```text
1.4.3 投标人不得存在下列情形之一：
（1）为招标人不具有独立法人资格的附属机构；
（2）为本招标项目前期准备提供设计或咨询服务；
1.4.4 其他条款
```

断言废标项包含两个子条款，而不是只包含标题句。

- [ ] **Step 2: 建立章节范围提取器**

当命中 `投标人不得存在`、`否决其投标`、`不予受理` 这类父标题时，提取到下一个同级条款或更高层级标题为止。

- [ ] **Step 3: AI review 的候选单位改为“完整条款块”**

`rejection_clause_review` 的 candidate `content` 应是完整条款块，`sourceText` 包含父标题和子条款范围，`evidenceIds` 覆盖父标题和子条款。

---

## Task 6: 商务评分改为行级或区段级边界，禁止整表展开

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_workflow.py`
- Test: `code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`

- [ ] **Step 1: 写评分边界测试**

构造 `评标办法前附表`：

- `2.2.4（1） 商务评分标准` 3 行。
- `2.2.4（2） 技术评分标准` 多行。
- `2.2.4（3） 投标报价评分标准` 多行。

断言：

```python
self.assertEqual(len(scoring["business"]), 3)
self.assertFalse(any("技术" in row["evidence"] for row in scoring["business"]))
self.assertFalse(any("报价" in row["evidence"] for row in scoring["business"]))
```

- [ ] **Step 2: 把 `scoring_table_review` 从表级裁判改为行级裁判**

候选不再是整表 `SCORING-TABLE-REVIEW-0001`，而是：

```text
SCORING-ROW-REVIEW-{table}-{row}
```

每个 candidate 带：

- `clauseNo`
- `scoreGroup`
- `rowIndex`
- `evidenceIds`

- [ ] **Step 3: 合成时只展开 business 行**

`_append_scoring_from_accepted_tables()` 改名或替换为 `_append_scoring_from_accepted_rows()`。只接受：

```python
scoreGroup == "business"
```

或条款号落在：

```text
2.2.4（1）
```

不得因为整表包含商务评分就把技术、报价、符合性审查一起放入 `scoringCriteria.business`。

---

## Task 7: 前端同步新契约，只展示存在的商务评分

**Files:**
- Modify: `code/sewpg-bid-frontend/src/workspaces/business/pages/BusinessTenderReview.jsx`
- Test: `code/sewpg-bid-frontend/src/workspaces/business/pages/BusinessTenderReview.test.jsx` 或现有前端测试入口

- [ ] **Step 1: 写展示契约测试**

输入：

```js
scoringCriteria: {
  business: [{ scoringItem: '交货期保证' }]
}
```

断言页面显示商务评分，不显示：

- `投标报价评分标准`
- `符合性审查标准`

- [ ] **Step 2: 删除商务页固定 price/compliance 分组**

`BUSINESS_REVIEW_CONFIG.scoringGroups` 只保留：

```js
[['business', '商务评分标准']]
```

或改成按 `Object.keys(scoringCriteria)` 动态渲染，但 business 工作区默认只允许 `business`。

---

## Task 8: 端到端验收

**Files:**
- Test: `code/sewpg-bid-backend/tests/test_parse_pipeline.py`
- Test fixture: 使用 `tmp/debug_business_parser_wenxi` 复现数据或新建稳定 fixture。

- [ ] **Step 1: 后端验收断言**

同一份商务招标文件解析后必须满足：

```python
self.assertEqual(workflow["validationStatus"], "passed")
self.assertEqual(workflow["stage"], "finalized")
self.assertFalse(workflow.get("backendFallbackTransformApplied"))
self.assertEqual(tenderer_field["value"], "山西漳山发电有限责任公司")
self.assertTrue(bid_deadline_field.get("evidenceIds"))
self.assertGreater(len(field_groups["qualificationRequirements"]), 0)
self.assertTrue(all(row.get("evidenceIds") for row in scoring["business"]))
```

- [ ] **Step 2: 验证命令**

```bash
cd code/sewpg-bid-backend
pytest tests/test_business_parse_skill_script.py tests/test_parse_pipeline.py -q
```

前端：

```bash
cd code/sewpg-bid-frontend
npm test -- BusinessTenderReview
```

---

## 完成标准

- `validation_report.status = "passed"`。
- `workflow.stage = "finalized"`。
- `backendFallbackTransformApplied` 不再出现在新版 skill 成功链路中。
- 项目基础信息来自准确条款，且每个 found 字段都有来源。
- 资格要求来自 AI accepted candidates，不再被旧兜底清空。
- 商务废标项能展开父标题下的具体子条款。
- `scoringCriteria.business` 只包含商务评分行，不混入技术、报价、符合性审查。
- 前端不再硬编码展示报价评分和符合性审查分组。
