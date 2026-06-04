# 商务标 S1 AI 语义裁判工作流边界实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通 `bid-business-tender-structured-parser` 新版 workflow 的最终链路，确保 `workflow.stage = "finalized"` 的 AI 语义审查结果进入最终 API 和前端展示，并把脚本职责限制在候选召回、证据锚定、验真和合成。

**Architecture:** 商务解析采用“脚本准备证据 -> AI 语义裁判 -> 脚本验真 -> 脚本合成 -> 后端原样交付 finalized 结果”的主链路。脚本不得用关键词补丁直接决定“是否是资格要求/废标项/评分项”，只能给 AI 提供足够上下文并验证 AI 选中的内容来自候选证据；旧 `_transform_to_business_contract()` 只作为 skill 失败、无 workflow 或无 AI 决策时的兜底。

**Tech Stack:** Python 3、FastAPI、pytest/unittest、现有 `bid-business-tender-structured-parser`、`business_workflow.py`、`candidate_package.json`、`ai_tasks/*.json`、`ai_decisions/*.json`、`validation_report.json`。

---

## 核心原则

脚本只负责召回、定位、验真、合成；“是不是资格要求 / 废标项 / 评分项 / 投标人须知 / 材料要求 / 承诺 / 普通流程说明 / 无关内容”必须交给 AI 语义审查层裁判，不能再靠关键词补丁硬筛。

禁止新增或继续扩展这类规则作为最终业务判断：

- “包含某词就剔除”。
- “包含某词就一定归入废标项”。
- “某章节一定算资格要求”。
- “某类表格一定进入最终评分表”。
- “为了修正一个模块，把被拒绝内容塞进另一个模块”。

允许脚本使用关键词、标题、表头、编号和位置做候选召回与证据分组，但这些只是 `candidate_package.json` 的候选来源类型和召回线索，不是最终业务分类结论。

## 当前根因

现象不是 skill 完全没跑。已有证据表明新版 workflow 至少运行到了候选包和验真产物阶段：

- 容器 `sewpg_bid_opencode` 中有新版 `business_workflow.py`。
- 项目目录已生成 `candidate_package.json`、`validation_report.json`、`s1_parse_manifest.json`。
- 最终结果里 `targetSkill=bid-business-tender-structured-parser` 且 `mode=opencode-skill`。

主因是后端在 skill 返回后又执行 `_transform_to_business_contract(..., run_semantic_review=True)`，把 workflow 合成后的结果覆盖回旧本地商务解析逻辑。只要 `structured.mode == "opencode-skill"` 就二次转换，会导致：

- `structured.workflow` 丢失或为空。
- `validation_report.json` 未进入最终前端可见结构。
- 已被 workflow 拒绝的污染项重新出现在 `s1_structured_result.json`。

## 文件结构

- Modify: `code/sewpg-bid-backend/app/services/parsing.py`
  - 让 `structured.workflow.stage = "finalized"` 的 skill 结果成为权威输出，不再进入旧 `_transform_to_business_contract()` 覆盖核心字段。
  - 仅在 skill 失败、无 workflow、workflow 未 finalized、无 AI 决策或显式 fallback 时调用旧 transform。

- Modify: `code/sewpg-bid-backend/tests/test_parse_pipeline.py`
  - 增加后端链路测试：finalized workflow 不被二次转换覆盖，`structured.workflow` 保留。

- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_workflow.py`
  - 升级候选包字段，给 AI 足够上下文。
  - 拆分/强化 AI 审查任务契约。
  - 确保 finalizer 只使用 AI `accepted` 且脚本验真的内容进入最终展示字段。

- Modify: `code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`
  - 增加 workflow 合同测试、候选包上下文测试、AI 决策 accepted/rejected/needsReview 测试、最终展示污染隔离测试。

- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/SKILL.md`
  - 固化“AI 裁判、脚本供证和验真”的泛化边界，禁止关键词硬筛作为最终判断。

---

### Task 1: 先打通 finalized 主链路

**Files:**
- Modify: `code/sewpg-bid-backend/tests/test_parse_pipeline.py`
- Modify: `code/sewpg-bid-backend/app/services/parsing.py`

- [ ] **Step 1: 写失败测试，证明 finalized workflow 不能被旧 transform 覆盖**

在后端解析链路测试中构造或 mock 一个 opencode skill 返回结果：

```json
{
  "schemaVersion": "bid-business-tender-structured-v1",
  "targetSkill": "bid-business-tender-structured-parser",
  "structured": {
    "mode": "opencode-skill",
    "workflow": {
      "stage": "finalized",
      "candidatePackagePath": "/data/parsed/PRJ-TEST/candidate_package.json",
      "validationReportPath": "/data/parsed/PRJ-TEST/validation_report.json",
      "aiDecisionsDir": "/data/parsed/PRJ-TEST/ai_decisions",
      "validationStatus": "passed"
    },
    "fieldGroups": {
      "qualificationRequirements": [
        {
          "order": 1,
          "content": "AI 已接收的资格要求",
          "applicableScope": "全部标段",
          "sourceText": "招标文件第二章 > 投标人资格要求第 1 条",
          "evidenceIds": ["DOC-1:L10"]
        }
      ],
      "commercialRejectionClauses": [],
      "bidderInstructions": []
    },
    "aiDecisions": {
      "qualification_review": {
        "accepted": ["QUAL-DOC-1-0001"],
        "rejected": ["QUAL-DOC-1-0002"]
      }
    }
  }
}
```

断言最终 API / `s1_structured_result.json` 中仍保留：

- `structured.workflow.stage == "finalized"`。
- `structured.workflow.validationReportPath`。
- `structured.fieldGroups.qualificationRequirements[0].content == "AI 已接收的资格要求"`。
- 不出现旧 `_transform_to_business_contract()` 重新生成的污染项。

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd code/sewpg-bid-backend
python -m pytest tests/test_parse_pipeline.py -q
```

Expected: FAIL。失败原因应显示 finalized workflow 被二次转换覆盖，或 `structured.workflow` 丢失。

- [ ] **Step 3: 修改后端分流条件**

在 `app/services/parsing.py` 中把当前逻辑：

```python
should_finalize_business_semantics = (
    profile.key == "business"
    and isinstance(structured_result.get("structured"), dict)
    and (
        str(structured_result["structured"].get("mode") or "").strip() == "opencode-skill"
        or (settings.s1_parse_opencode_enabled and bool(skill_warning))
    )
)
```

改成语义更明确的分流：

```python
structured_payload = structured_result.get("structured")
workflow_payload = structured_payload.get("workflow") if isinstance(structured_payload, dict) else {}
workflow_stage = str(workflow_payload.get("stage") or "").strip() if isinstance(workflow_payload, dict) else ""
skill_mode = str(structured_payload.get("mode") or "").strip() if isinstance(structured_payload, dict) else ""

skill_finalized_business_workflow = (
    profile.key == "business"
    and skill_mode == "opencode-skill"
    and workflow_stage == "finalized"
)

should_finalize_business_semantics = (
    profile.key == "business"
    and isinstance(structured_payload, dict)
    and not skill_finalized_business_workflow
    and (
        skill_mode == "opencode-skill"
        or (settings.s1_parse_opencode_enabled and bool(skill_warning))
    )
)
```

规则：如果 `structured.workflow.stage = "finalized"`，后端不得再调用旧 transform 覆盖核心字段；旧 transform 只作为 skill 失败、无 workflow、无 AI 决策或未 finalized 时的兜底。

- [ ] **Step 4: 运行测试确认通过**

Run:

```bash
cd code/sewpg-bid-backend
python -m pytest tests/test_parse_pipeline.py tests/test_business_parse_skill_script.py -q
```

Expected: PASS。

---

### Task 2: 明确 AI 语义审查层职责

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_workflow.py`
- Modify: `code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`

- [ ] **Step 1: 写 AI task 合同测试**

测试 `ai_tasks/*.json` 中每个任务都要求 AI 输出以下字段：

- `decision`: `accepted` / `rejected` / `needsReview`。
- `fieldType`: 例如 `qualification_requirement`、`rejection_clause`、`scoring_item`、`bidder_instruction`、`material_requirement`、`commitment`、`process_note`、`irrelevant`。
- `content`：要求内容。
- `applicableScope`：适用范围。
- `sourceText`：可读来源文字。
- `evidenceIds`：候选证据 ID。
- `reason`：语义判断理由，不能只是关键词命中理由。

- [ ] **Step 2: 强化任务说明**

AI 不是补充描述，也不是生成漂亮文字，而是结构化裁判。任务说明必须要求 AI 判断：

- 候选属于哪一类：资格要求、废标项、评分项、投标人须知、材料要求、承诺、普通流程说明、无关内容。
- 是否应该进入最终展示。
- 适用范围：例如标段一至标段四、标段五、全部标段。
- 可读来源文字。
- 对不确定内容输出 `needsReview`，不得强行塞进某个最终字段。

---

### Task 3: 调整脚本边界

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_workflow.py`
- Modify: `code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`

- [ ] **Step 1: 写边界测试**

构造包含以下候选的样本：

- 真资格要求。
- 投标管家、联系人、CA 办理、目录项。
- 异议投诉流程。
- 普通说明。
- 评分表。
- 连续编号三条要求，其中第三条紧随第 18、19 条之后。

测试要求：

- 脚本可以把这些内容召回到 `candidate_package.json`。
- 脚本不得在没有 AI `accepted` 决策时把候选直接写进最终 `qualificationRequirements`、`commercialRejectionClauses` 或 `scoringCriteria`。
- AI `rejected` 的候选必须在 `ai_decisions` 或 `validation_report.json` 中保留拒绝理由。

- [ ] **Step 2: 限定脚本职责**

脚本保留三类能力：

- 候选召回：尽量多捞出可能相关的段落、表格行、编号项、跨页续段。
- 证据锚定：保留原文、章节路径、页码或位置、邻近上下文。
- 结果验真：检查 AI 选中的内容必须来自候选证据，不能凭空生成。

脚本 finalizer 允许拒绝不合约的 AI `accepted` 项，但不得自行把未被 AI 接收的候选升级成最终业务项。

---

### Task 4: 升级 candidate_package 上下文

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_workflow.py`
- Modify: `code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`

- [ ] **Step 1: 写候选包结构测试**

每个候选至少包含：

- `candidateId`
- `rawText` 或 `text`
- `beforeText`
- `afterText`
- `sectionPath`
- `tableTitle`
- `tableHeaders`
- `page` 或 `location`
- `sourceType`：`body`、`table`、`toc`、`header_footer` 等。
- `neighborItems`：相邻编号项，避免“三条只识别两条”。
- `evidenceIds`

- [ ] **Step 2: 完善候选构建**

候选包要给 AI 足够上下文，而不是只给碎片文本。表格行候选必须带表题、表头和行位置；编号段落候选必须带前后编号项；跨页续段必须保留相邻上下文。

---

### Task 5: 重写 AI 审查任务，而不是写过滤规则

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_workflow.py`
- Modify: `code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`

- [ ] **Step 1: 统一 AI task 模块**

保留或兼容以下模块任务：

- `qualification_review`
- `rejection_clause_review`
- `scoring_review`
- `bidder_instruction_review`（若代码已有 `bidder_instructions_review`，保留兼容别名并在输出中统一到一个 canonical task）
- `commitment_review`
- `project_fact_review`（若代码已有 `project_facts_review`，保留兼容别名并在输出中统一到一个 canonical task）

- [ ] **Step 2: 每个 task 输出裁判结果**

每个 task 都要求 AI 输出：

- 接收 / 拒绝 / 待审。
- 字段类型。
- 要求内容。
- 适用范围。
- 来源文字。
- 证据 ID。
- 判断理由。

重点是“语义判断理由”，不是关键词命中理由。

---

### Task 6: 最终展示只用 AI 接收并通过验真的内容

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_workflow.py`
- Modify: `code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`

- [ ] **Step 1: 写 finalizer 测试**

构造 AI 决策：

- `accepted`：真正资格要求、真正废标项、真正评分项。
- `rejected`：投标管家、联系人、CA 办理、目录项、异议投诉流程、普通说明。
- `needsReview`：边界不确定条款。

断言：

- 最终展示字段只使用 `accepted` 且验真通过的内容。
- `rejected` 不进入最终展示字段，但能在 `ai_decisions` 或 `validation_report.json` 中看到拒绝理由。
- `needsReview` 不被强行塞入资格/废标/评分字段，应进入复核结构或报告。

- [ ] **Step 2: 统一可读来源**

前端展示字段来源必须来自 AI 审查后的 `sourceText`，并经脚本验真。例如：

```text
招标文件第二章“投标人资格要求”，标段一至标段四资格要求第 3 条
```

不要展示裸行号、裸块号或内部 evidence ID。资格要求最终四列：

- 序号
- 要求内容
- 适用范围
- 来源

废标项、评分表也同理，最终展示来自“AI 已接收 + 脚本已验真”的结果。

---

### Task 7: 真实样本验收

**Files:**
- Read: `/data/parsed/<projectId>/s1_structured_result.json`
- Read: `/data/parsed/<projectId>/candidate_package.json`
- Read: `/data/parsed/<projectId>/validation_report.json`
- Read: `/data/parsed/<projectId>/ai_decisions/*.json`

- [ ] **Step 1: 重新运行真实项目解析**

优先用当前后端 API 或页面重新跑一次商务解析。若只能在容器内验证，使用项目实际 `s1_parse_manifest.json` 复跑 `s1parse <manifest>`。

- [ ] **Step 2: 检查最终 JSON**

验收标准：

- `s1_structured_result.json` 保留 `structured.workflow.stage = "finalized"`。
- `structured.workflow.validationReportPath` 指向真实存在的 `validation_report.json`。
- `qualificationRequirements` 不再混入投标管家、联系人、CA 办理、目录项。
- 废标项不再混入异议投诉流程、普通说明。
- 评分表不被资格要求或废标内容污染。
- 针对“标段一至标段四需同时满足”这种连续多条，不能漏最后一条。
- 被剔除内容能在 `ai_decisions` 中看到拒绝理由。

- [ ] **Step 3: 检查前端展示**

前端商务解析页应展示 finalized workflow 的最终字段。资格要求展示四列：序号、要求内容、适用范围、来源；来源是中文可读文本，不是裸行号。

---

## 自检清单

- [ ] 是否先解决 finalized workflow 被后端覆盖的问题。
- [ ] 是否没有新增关键词硬筛作为最终业务判断。
- [ ] 是否明确脚本只负责召回、定位、验真、合成。
- [ ] 是否明确 AI 负责语义裁判：分类、接收/拒绝/待审、适用范围、来源文字、理由。
- [ ] 是否升级候选包上下文，而不是只传碎片文本。
- [ ] 是否 finalizer 只使用 AI accepted 且脚本验真的内容。
- [ ] 是否保留 rejected / needsReview 的理由供验收追溯。
- [ ] 是否用真实解析结果验收，而不只看测试通过。
