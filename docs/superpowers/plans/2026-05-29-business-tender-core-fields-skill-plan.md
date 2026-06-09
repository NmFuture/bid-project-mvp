# 商务解析核心字段 Skill 改造 Implementation Plan

> **已废弃 / Superseded:** 本计划的部分任务仍把资格要求、废标项等语义分类交给脚本关键词和硬规则，已不符合当前边界。后续不得按本计划继续实现商务 S1 语义分类。请改用 `docs/superpowers/plans/2026-05-31-business-s1-ai-semantic-workflow-boundary-plan.md`：脚本负责召回、定位、验真、合成；AI 负责接收/拒绝/待审和模块归属裁判；后端不得覆盖 `workflow.stage = "finalized"` 的 skill 结果。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改前端的前提下，改进商务解析 Skill，使其复用现有 DOCX 段落/表格解析底座，稳定产出项目基础信息、资格要求、投标人须知前附表、商务废标项和现有商务评分细则。

**Architecture:** 现有解析器已经把 DOCX 拆成段落块和表格块，并能识别符合性审查、投标报价评分、商务评分三类评分表。本计划在第一层解析结果之后增加“核心商务展示归并层”：优先复用已有 `scoringCriteria`、`projectDates`、`qualificationSupport` 和基础字段，只有缺失或明显误抽时才回到 DOCX block 补查。Skill 脚本和后端本地兜底逻辑保持同一 contract，避免不同运行模式输出不一致。

**Tech Stack:** Python 3、python-docx、unittest/pytest、现有 `bid-business-tender-structured-parser`、现有 `parser_core` DOCX block 解析能力。

---

## 文件结构

- Modify: `C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_contract.py`
  - Skill 主 contract 生成逻辑。
  - 新增“核心商务展示归并层”。
  - 复用 `parser_core` 的 DOCX block 读取能力，不新建第二套 DOCX 解析器。
- Modify: `C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/SKILL.md`
  - 更新 Skill 输出说明，明确新旧字段并存。
- Modify: `C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend/app/services/parsing.py`
  - 同步后端本地兜底商务 contract。否则未启用 opencode 时仍会输出旧字段。
- Modify: `C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`
  - 覆盖 Skill 脚本输出。
- Modify: `C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend/tests/test_s1parse_router_script.py`
  - 覆盖 router 调用商务 Skill 后的新 fieldGroups。
- Modify: `C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend/tests/test_parse_pipeline.py`
  - 覆盖后端本地兜底路径。
- Optional test artifact: `C:/Users/99065/Documents/商务标V2/解析增强/current_sample_structured_result.json`
  - 仅用于人工对照真实样本输出，不作为单测依赖。

## Contract 目标

新 contract 保留旧字段，同时新增面向商务解析页的核心字段：

```json
{
  "structured": {
    "fieldGroups": {
      "projectBasics": [
        {"key": "projectName", "label": "项目名称"},
        {"key": "tenderNo", "label": "招标编号"},
        {"key": "tenderer", "label": "招标人"},
        {"key": "tenderAgency", "label": "招标代理机构"},
        {"key": "bidDeadline", "label": "递交截止时间"}
      ],
      "qualificationRequirements": [],
      "bidderInstructions": [],
      "commercialRejectionClauses": [],
      "businessResponse": [],
      "qualificationSupport": [],
      "commitmentRequirements": []
    },
    "scoringCriteria": {
      "business": [],
      "price": [],
      "compliance": []
    }
  }
}
```

`scoringCriteria.business`、`scoringCriteria.price`、`scoringCriteria.compliance` 继续沿用现有识别结果，不重复识别。

---

### Task 1: 用测试锁住现有评分表识别不退化

**Files:**
- Modify: `C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`

- [ ] **Step 1: 增强 Skill 脚本测试样本**

在 `test_business_skill_script_outputs_business_contract` 的临时 Markdown 文本中补齐三类表标题和表格：

```python
"附表1：符合性审查标准表",
"| 序号 | 审查项目 | 审查标准 |",
"| --- | --- | --- |",
"| 1 | 投标保证金 | 按照招标文件要求提供投标保证金且无瑕疵。 |",
"附表3：商务评分标准表",
"| 序号 | 评分项 | 分值 | 得分点 | 证明材料要求 |",
"| --- | --- | --- | --- | --- |",
"| 1 | 企业业绩 | 20分 | 近三年同类风电项目业绩满足要求得满分。 | 提供合同或中标通知书。 |",
"附表4：投标报价评分标准",
"| 序号 | 评分项 | 分值 | 得分点 |",
"| --- | --- | --- | --- |",
"| 1 | 评标价 | 100分 | 评标价等于评标基准价时得100分。 |",
```

- [ ] **Step 2: 添加三类评分断言**

在现有 `scoringCriteria` 断言后增加：

```python
self.assertEqual(len(structured["scoringCriteria"]["compliance"]), 1)
self.assertEqual(structured["scoringCriteria"]["compliance"][0]["scoringItem"], "投标保证金")
self.assertEqual(len(structured["scoringCriteria"]["business"]), 1)
self.assertEqual(structured["scoringCriteria"]["business"][0]["scoringItem"], "企业业绩")
self.assertEqual(len(structured["scoringCriteria"]["price"]), 1)
self.assertEqual(structured["scoringCriteria"]["price"][0]["scoringItem"], "评标价")
```

- [ ] **Step 3: 运行测试确认当前行为**

Run:

```bash
cd C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend
python -m pytest tests/test_business_parse_skill_script.py -q
```

Expected:

```text
PASS 或仅新断言暴露真实缺口；不应出现脚本无法执行、JSON 无法生成等基础错误。
```

---

### Task 2: 新增核心字段测试，先让测试失败

**Files:**
- Modify: `C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`

- [ ] **Step 1: 在测试样本中加入前附表、代理机构、截止时间和废标条款**

在临时 Markdown 文本中加入：

```python
"投标人须知前附表",
"| 条款号 | 条款名称 | 编列内容 |",
"| --- | --- | --- |",
"| 1.1.2 | 招标人 | 招标人：华能集团 |",
"| 1.1.3 | 招标代理机构 | 招标代理机构：睿采数动公司 |",
"| 1.1.4 | 招标项目名称 | 华能甘肃100MW风电项目 |",
"| 4.2.1 | 投标截止时间 | 2026年1月26日09时00分 |",
"投标文件应当对招标文件的实质性要求作出响应，否则投标将被否决。",
"电子投标文件逾期上传或者未成功上传指定信息平台，招标人不予受理。",
```

- [ ] **Step 2: 添加新 fieldGroups 断言**

新增辅助函数：

```python
def field_by_key(fields: list[dict], key: str) -> dict:
    return next(field for field in fields if field["key"] == key)
```

新增断言：

```python
field_groups = structured["fieldGroups"]
self.assertIn("qualificationRequirements", field_groups)
self.assertIn("bidderInstructions", field_groups)
self.assertIn("commercialRejectionClauses", field_groups)

project_basics = field_groups["projectBasics"]
self.assertEqual(field_by_key(project_basics, "projectName")["value"], "华能甘肃100MW风电项目")
self.assertEqual(field_by_key(project_basics, "tenderNo")["value"], "HN-BUS-2026-001")
self.assertEqual(field_by_key(project_basics, "tenderer")["value"], "华能集团")
self.assertEqual(field_by_key(project_basics, "tenderAgency")["value"], "睿采数动公司")
self.assertEqual(field_by_key(project_basics, "bidDeadline")["value"], "2026-01-26")

self.assertGreaterEqual(len(field_groups["qualificationRequirements"]), 1)
self.assertEqual(field_groups["bidderInstructions"][0]["clauseNo"], "1.1.2")
self.assertEqual(field_groups["bidderInstructions"][1]["clauseName"], "招标代理机构")
self.assertGreaterEqual(len(field_groups["commercialRejectionClauses"]), 2)
self.assertTrue(any("否决" in row["content"] for row in field_groups["commercialRejectionClauses"]))
self.assertTrue(any("不予受理" in row["content"] for row in field_groups["commercialRejectionClauses"]))
```

- [ ] **Step 3: 运行测试确认失败点明确**

Run:

```bash
cd C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend
python -m pytest tests/test_business_parse_skill_script.py -q
```

Expected:

```text
FAIL，失败原因应是缺少 qualificationRequirements、bidderInstructions、commercialRejectionClauses、tenderAgency 或 bidDeadline。
```

---

### Task 3: 在 Skill contract 中新增核心商务展示归并层

**Files:**
- Modify: `C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_contract.py`

- [ ] **Step 1: 扩展项目基础字段**

将 `PROJECT_BASIC_FIELDS` 调整为核心展示字段：

```python
PROJECT_BASIC_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("projectName", "项目名称", ("项目名称", "招标项目名称")),
    FieldSpec("tenderNo", "招标编号", ("招标编号", "项目编号", "招标文件编号")),
    FieldSpec("tenderer", "招标人", ("招标人", "业主", "建设单位", "项目单位")),
    FieldSpec("tenderAgency", "招标代理机构", ("招标代理机构", "代理机构")),
    FieldSpec("bidDeadline", "递交截止时间", ("递交截止时间", "投标截止时间", "投标文件递交截止时间", "开标时间")),
)
```

旧的 `managementUnit`、`bidSectionScale`、`deliveryPeriod`、`warrantyPeriod` 不再作为商务解析页核心字段，但如果后续链路仍依赖，可在 `projectFactFields` 里保留已有来源。

- [ ] **Step 2: 增加引用型值过滤**

新增函数：

```python
def _is_reference_only_value(value: str) -> bool:
    normalized = re.sub(r"\s+", "", str(value or ""))
    return normalized in {
        "见投标人须知前附表",
        "详见招标公告",
        "详见技术规范书",
        "详见招标文件",
        "按招标文件要求",
    } or normalized.startswith("见投标人须知前附表")
```

- [ ] **Step 3: 增加核心字段候选排序**

新增函数，业务含义是“封面和前附表优先，目录和引用句降权”：

```python
def _business_core_field_score(item: dict[str, Any], spec: FieldSpec) -> int:
    value = str(item.get("value") or item.get("keyValue") or "").strip()
    section = str(item.get("section") or "")
    evidence = str(item.get("evidence") or "")
    location = str(item.get("evidenceLocation") or "")
    score = 0
    if location.startswith("B"):
        score += 40
    if section == "封面":
        score += 80
    if "投标人须知前附表" in section:
        score += 70
    if "招标公告" in section or "联系方式" in section:
        score += 50
    if _is_reference_only_value(value):
        score -= 200
    if re.search(r"\d{4}-\d{2}-\d{2}|20\d{2}年", value):
        score += 30
    if spec.key == "tenderNo" and re.search(r"[A-Z]{2,}.*\d", value):
        score += 60
    if spec.key in {"tenderer", "tenderAgency"} and len(value) <= 80:
        score += 20
    if len(value) > 180:
        score -= 40
    if not value:
        score -= 300
    return score
```

- [ ] **Step 4: 改造项目基础字段构建**

将 `_build_business_project_basics` 改为“候选打分取最优”，并对 `bidDeadline` 优先使用 `projectDates.endDate`：

```python
def _build_business_project_basics(
    items: list[dict[str, Any]],
    project_dates: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    project_dates = project_dates or {}
    fields: list[dict[str, Any]] = []
    for spec in PROJECT_BASIC_FIELDS:
        if spec.key == "bidDeadline":
            value = str(project_dates.get("endDate") or "").strip()
            if value:
                field = _empty_business_field(spec, value=value)
                field["status"] = "found"
                field["confidence"] = 0.78
                fields.append(field)
                continue
        candidates = [
            item
            for item in items
            if any(alias in " ".join(str(item.get(key) or "") for key in ("title", "keyEntity", "evidence", "section")) for alias in spec.aliases)
        ]
        matched = max(candidates, key=lambda item: _business_core_field_score(item, spec)) if candidates else None
        if matched and _business_core_field_score(matched, spec) > -50:
            fields.append(_business_field_from_item(spec, matched))
        else:
            fields.append(_empty_business_field(spec))
    return fields
```

- [ ] **Step 5: 在 `build_business_result` 中传入 project_dates**

把 field_groups 构建顺序调整为先取 `project_dates`，再构建 `projectBasics`：

```python
project_dates = structured.get("projectDates") if isinstance(structured.get("projectDates"), dict) else {}
field_groups = {
    "projectBasics": _build_business_project_basics(merged_items, project_dates),
    "businessResponse": _build_business_response_fields(merged_items),
    "qualificationSupport": _build_qualification_support_fields(merged_items),
    "qualificationRequirements": _build_qualification_requirements(merged_items),
    "bidderInstructions": _extract_bidder_instruction_rows(documents),
    "commercialRejectionClauses": _extract_commercial_rejection_clauses(documents, texts_by_id),
    "commitmentRequirements": _build_commitment_requirement_fields(merged_items),
}
```

此时 `_build_qualification_requirements`、`_extract_bidder_instruction_rows`、`_extract_commercial_rejection_clauses` 还未实现，下一任务补齐。

---

### Task 4: 参照评分表机制提取投标人须知前附表

**Files:**
- Modify: `C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_contract.py`

- [ ] **Step 1: 复用 `parser_core._iter_docx_blocks`**

修改 import：

```python
from parser_core import _iter_docx_blocks, parse_manifest as parse_technical_manifest  # type: ignore[import-not-found]
```

- [ ] **Step 2: 新增前附表识别函数**

新增函数：

```python
def _looks_like_bidder_instruction_table(title: str, rows: list[list[str]]) -> bool:
    title_text = _clean(title)
    header_text = "".join("".join(_clean(cell) for cell in row) for row in rows[:2])
    return "投标人须知前附表" in title_text and all(token in header_text for token in ("条款", "编列"))
```

- [ ] **Step 3: 新增前附表逐行转换函数**

新增函数：

```python
def _parse_bidder_instruction_rows(
    rows: list[list[str]],
    *,
    document: dict[str, Any],
    section: str,
    block_index: int,
) -> list[dict[str, Any]]:
    cleaned_rows = [[_clean(cell) for cell in row] for row in rows if any(_clean(cell) for cell in row)]
    if len(cleaned_rows) <= 1:
        return []
    header = cleaned_rows[0]
    data_rows = cleaned_rows[1:]
    parsed: list[dict[str, Any]] = []
    for row_index, row in enumerate(data_rows, start=2):
        if len(row) < 3:
            continue
        clause_no = row[0]
        clause_name = row[1]
        content = " ".join(cell for cell in row[2:] if cell).strip()
        if not clause_no and not clause_name and not content:
            continue
        parsed.append(
            {
                "id": f"BIDDER-INST-{len(parsed) + 1:04d}",
                "clauseNo": clause_no,
                "clauseName": clause_name,
                "content": content,
                "sourceFile": str(document.get("name") or ""),
                "sourceDocumentId": str(document.get("id") or ""),
                "section": section,
                "evidence": "；".join(f"{header[i]}：{cell}" if i < len(header) and header[i] else cell for i, cell in enumerate(row) if cell),
                "evidenceLocation": f"B{block_index}/R{row_index}",
                "confidence": 0.9,
            }
        )
    return parsed
```

- [ ] **Step 4: 新增前附表抽取入口**

新增函数：

```python
def _extract_bidder_instruction_rows(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    for document in documents:
        source_path = Path(str(document.get("sourcePath") or ""))
        blocks = _iter_docx_blocks(source_path)
        current_section = ""
        for block_index, block in enumerate(blocks, start=1):
            if block.get("type") == "paragraph":
                text = _clean(block.get("text"))
                if text:
                    current_section = text
                continue
            if block.get("type") != "table":
                continue
            rows = block.get("rows") or []
            if _looks_like_bidder_instruction_table(current_section, rows):
                rows_out.extend(_parse_bidder_instruction_rows(rows, document=document, section=current_section, block_index=block_index))
                break
    return rows_out
```

- [ ] **Step 5: 运行 Skill 脚本测试**

Run:

```bash
cd C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend
python -m pytest tests/test_business_parse_skill_script.py -q
```

Expected:

```text
前附表相关断言通过；若 Markdown 测试无法覆盖 DOCX block，补一个用 python-docx 生成临时 DOCX 的测试。
```

---

### Task 5: 归并资格要求与商务废标项

**Files:**
- Modify: `C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_contract.py`

- [ ] **Step 1: 新增资格要求归并函数**

新增函数，优先复用已有 `qualificationSupport` 命中项：

```python
def _build_qualification_requirements(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keywords = ("投标人资格要求", "资格要求", "资格能力要求", "投标人资质条件", "合格投标人", "资格审查")
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        text = " ".join(str(item.get(key) or "") for key in ("title", "keyEntity", "value", "evidence", "section"))
        if not any(keyword in text for keyword in keywords):
            continue
        content = str(item.get("value") or item.get("evidence") or "").strip()
        if not content or content in seen:
            continue
        seen.add(content)
        matched.append(
            {
                "id": f"QUAL-{len(matched) + 1:04d}",
                "title": str(item.get("title") or "投标人资格要求"),
                "content": content,
                **_copy_meta_fields(item),
                "confidence": float(item.get("confidence") or 0.78),
            }
        )
    return matched[:12]
```

- [ ] **Step 2: 新增商务废标项关键词**

新增常量：

```python
COMMERCIAL_REJECTION_KEYWORDS = (
    "否决",
    "废标",
    "无效投标",
    "不予受理",
    "★",
    "实质性响应",
    "投标人不得存在",
    "不得存在下列情形",
)
```

- [ ] **Step 3: 新增商务废标项提取函数**

新增函数：

```python
def _extract_commercial_rejection_clauses(
    documents: list[dict[str, Any]],
    texts_by_id: dict[str, str],
) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = []
    seen: set[str] = set()
    for document in documents:
        document_id = str(document.get("id") or "")
        source_file = str(document.get("name") or document_id or "招标文件")
        current_section = ""
        for line_number, raw_line in enumerate(str(texts_by_id.get(document_id) or "").splitlines(), start=1):
            line = _clean(raw_line)
            if not line:
                continue
            if _looks_like_section_heading(line):
                current_section = line
            if not any(keyword in line for keyword in COMMERCIAL_REJECTION_KEYWORDS):
                continue
            if line in seen:
                continue
            seen.add(line)
            matched_keywords = [keyword for keyword in COMMERCIAL_REJECTION_KEYWORDS if keyword in line]
            clauses.append(
                {
                    "id": f"REJECT-{len(clauses) + 1:04d}",
                    "title": current_section or "商务废标项",
                    "content": line,
                    "matchedKeywords": matched_keywords,
                    "riskLevel": "high" if any(keyword in matched_keywords for keyword in ("否决", "废标", "无效投标", "不予受理")) else "medium",
                    "sourceFile": source_file,
                    "sourceDocumentId": document_id,
                    "section": current_section,
                    "evidence": line,
                    "evidenceLocation": f"L{line_number}",
                    "confidence": 0.82,
                }
            )
    return clauses
```

- [ ] **Step 4: 运行 Skill 脚本测试**

Run:

```bash
cd C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend
python -m pytest tests/test_business_parse_skill_script.py -q
```

Expected:

```text
qualificationRequirements、commercialRejectionClauses 相关断言通过。
```

---

### Task 6: 同步后端本地兜底路径

**Files:**
- Modify: `C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend/app/services/parsing.py`
- Modify: `C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend/tests/test_parse_pipeline.py`

- [ ] **Step 1: 在 `parsing.py` 同步核心逻辑**

把 Task 3、Task 4、Task 5 中新增的业务逻辑同步到 `parsing.py` 的商务 contract 区域：

```python
PROJECT_BASIC_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("projectName", "项目名称", ("项目名称", "招标项目名称")),
    FieldSpec("tenderNo", "招标编号", ("招标编号", "项目编号", "招标文件编号")),
    FieldSpec("tenderer", "招标人", ("招标人", "业主", "建设单位", "项目单位")),
    FieldSpec("tenderAgency", "招标代理机构", ("招标代理机构", "代理机构")),
    FieldSpec("bidDeadline", "递交截止时间", ("递交截止时间", "投标截止时间", "投标文件递交截止时间", "开标时间")),
)
```

在 `_transform_to_business_contract` 中输出新增字段：

```python
field_groups = {
    "projectBasics": _build_business_project_basics(merged_items, project_dates),
    "businessResponse": _build_business_response_fields(merged_items),
    "qualificationSupport": _build_qualification_support_fields(merged_items),
    "qualificationRequirements": _build_qualification_requirements(merged_items),
    "bidderInstructions": _extract_bidder_instruction_rows(documents),
    "commercialRejectionClauses": _extract_commercial_rejection_clauses(documents, texts_by_id),
    "commitmentRequirements": _build_commitment_requirement_fields(
        merged_items,
        analysis=commitment_analysis,
    ),
}
```

- [ ] **Step 2: 更新本地 pipeline 测试**

在 `test_business_bid_parse_returns_business_contract_without_technical_groups` 或相邻商务解析测试中添加：

```python
self.assertIn("qualificationRequirements", field_groups)
self.assertIn("bidderInstructions", field_groups)
self.assertIn("commercialRejectionClauses", field_groups)
self.assertIn("tenderAgency", {field["key"] for field in field_groups["projectBasics"]})
self.assertIn("bidDeadline", {field["key"] for field in field_groups["projectBasics"]})
```

- [ ] **Step 3: 运行本地 pipeline 测试**

Run:

```bash
cd C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend
python -m pytest tests/test_parse_pipeline.py::ParsePipelineTests::test_business_bid_parse_returns_business_contract_without_technical_groups -q
```

Expected:

```text
PASS。商务本地兜底路径与 Skill 脚本输出同一组核心字段。
```

---

### Task 7: 更新 router 和容器脚本相关断言

**Files:**
- Modify: `C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend/tests/test_s1parse_router_script.py`
- Modify: `C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend/tests/test_s1parse_container_integration.py`

- [ ] **Step 1: 更新 fieldGroups key 断言**

把旧断言：

```python
self.assertEqual(
    list(structured["fieldGroups"].keys()),
    ["projectBasics", "businessResponse", "qualificationSupport", "commitmentRequirements"],
)
```

改为兼容新旧并存：

```python
field_group_keys = list(structured["fieldGroups"].keys())
self.assertIn("projectBasics", field_group_keys)
self.assertIn("businessResponse", field_group_keys)
self.assertIn("qualificationSupport", field_group_keys)
self.assertIn("commitmentRequirements", field_group_keys)
self.assertIn("qualificationRequirements", field_group_keys)
self.assertIn("bidderInstructions", field_group_keys)
self.assertIn("commercialRejectionClauses", field_group_keys)
```

- [ ] **Step 2: 运行 router 脚本测试**

Run:

```bash
cd C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend
python -m pytest tests/test_s1parse_router_script.py -q
```

Expected:

```text
PASS。router 仍能调用商务 Skill，并输出新旧并存 contract。
```

---

### Task 8: 更新 Skill 文档说明

**Files:**
- Modify: `C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/SKILL.md`

- [ ] **Step 1: 更新 description**

将 description 调整为：

```yaml
description: Parse one or more business tender documents into business-specific structured requirements, core review fields, bidder instruction table rows, commercial rejection clauses, scoring tables, commitment letters, and source evidence.
```

- [ ] **Step 2: 更新完整输出说明**

在 “The full output JSON must preserve” 列表中补充：

```markdown
- `structured.fieldGroups.projectBasics` for project name, tender number, tenderer, tender agency, and bid deadline. Prefer cover table and bidder instruction preface table over generic full-text matches; do not use reference-only values such as `见投标人须知前附表` as final values.
- `structured.fieldGroups.qualificationRequirements[]` as concise bidder qualification requirement rows, reusing existing qualification support evidence where possible.
- `structured.fieldGroups.bidderInstructions[]` as row-level records extracted from the `投标人须知前附表` table, with `clauseNo`, `clauseName`, `content`, and source evidence.
- `structured.fieldGroups.commercialRejectionClauses[]` as row-level commercial rejection/disqualification clauses matching `否决`, `废标`, `无效投标`, `不予受理`, `★`, `实质性响应`, `投标人不得存在`, or `不得存在下列情形`.
```

- [ ] **Step 3: 运行文档相关快速检查**

Run:

```bash
cd C:/Users/99065/Documents/商务标V2
rg -n "qualificationRequirements|bidderInstructions|commercialRejectionClauses|tenderAgency|bidDeadline" code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/SKILL.md
```

Expected:

```text
能搜索到新增 contract 字段。
```

---

### Task 9: 用真实样本回归并输出对照摘要

**Files:**
- Read: `C:/Users/99065/Documents/商务标V2/解析增强/current_sample_manifest.json`
- Generate: `C:/Users/99065/Documents/商务标V2/解析增强/current_sample_structured_result.after.json`
- Generate: `C:/Users/99065/Documents/商务标V2/解析增强/current_sample_summary.after.json`

- [ ] **Step 1: 复制 manifest 指向 after 输出**

使用现有 manifest 内容，把 `structuredResultPath` 改成：

```text
C:/Users/99065/Documents/商务标V2/解析增强/current_sample_structured_result.after.json
```

- [ ] **Step 2: 运行真实样本 Skill 脚本**

Run:

```bash
cd C:/Users/99065/Documents/商务标V2
python code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/run_from_manifest.py 解析增强/current_sample_manifest.after.json
```

Expected summary:

```json
{
  "schemaVersion": "bid-business-tender-structured-v1",
  "targetSkill": "bid-business-tender-structured-parser",
  "summary": {
    "scoringCounts": {
      "business": 11,
      "price": 2,
      "compliance": 13
    }
  }
}
```

- [ ] **Step 3: 检查真实样本核心字段**

Run:

```bash
cd C:/Users/99065/Documents/商务标V2
python - <<'PY'
import json
from pathlib import Path
p = Path("解析增强/current_sample_structured_result.after.json")
data = json.loads(p.read_text(encoding="utf-8"))
fg = data["structured"]["fieldGroups"]
print([field["key"] + "=" + str(field.get("value", "")) for field in fg["projectBasics"]])
print("qualificationRequirements", len(fg["qualificationRequirements"]))
print("bidderInstructions", len(fg["bidderInstructions"]))
print("commercialRejectionClauses", len(fg["commercialRejectionClauses"]))
print("business scoring", len(data["structured"]["scoringCriteria"]["business"]))
PY
```

Expected:

```text
projectName 不再是“见投标人须知前附表”
tenderAgency 有值
bidDeadline 为 2026-01-26
bidderInstructions 大于 0
commercialRejectionClauses 大于 0
business scoring 为 11
```

PowerShell 环境如果不支持 heredoc，改用 `@' ... '@ | python -`。

---

### Task 10: 全量相关测试与自检

**Files:**
- Read: changed files from previous tasks.

- [ ] **Step 1: 运行商务解析相关测试**

Run:

```bash
cd C:/Users/99065/Documents/商务标V2/code/sewpg-bid-backend
python -m pytest tests/test_business_parse_skill_script.py tests/test_s1parse_router_script.py tests/test_parse_pipeline.py::ParsePipelineTests::test_business_bid_parse_returns_business_contract_without_technical_groups -q
```

Expected:

```text
PASS。
```

- [ ] **Step 2: 搜索旧的严格 key 顺序断言**

Run:

```bash
cd C:/Users/99065/Documents/商务标V2
rg -n "\\[\"projectBasics\", \"businessResponse\", \"qualificationSupport\", \"commitmentRequirements\"\\]" code/sewpg-bid-backend/tests
```

Expected:

```text
无结果，或剩余结果已经确认不影响新旧并存 contract。
```

- [ ] **Step 3: 确认没有改前端**

Run:

```bash
cd C:/Users/99065/Documents/商务标V2
git diff -- code/sewpg-bid-frontend
```

Expected:

```text
无输出。
```

- [ ] **Step 4: 检查真实样本摘要**

确认 `C:/Users/99065/Documents/商务标V2/解析增强/current_sample_summary.after.json` 或控制台摘要中：

```text
商务评分、报价评分、符合性审查数量不下降。
项目名称、招标编号、招标人、代理机构、递交截止时间可直接阅读。
前附表和废标项是逐行结构，不是整章大段文本。
```

---

## Self-Review

**Spec coverage:**
- 项目基础信息：Task 3、Task 6、Task 9 覆盖。
- 资格要求：Task 5、Task 6、Task 9 覆盖。
- 投标人须知前附表：Task 4、Task 6、Task 9 覆盖。
- 商务废标项：Task 5、Task 6、Task 9 覆盖。
- 商务评分细则不退化：Task 1、Task 9、Task 10 覆盖。
- 不动前端：Task 10 明确检查。

**Placeholder scan:**
- 本计划未使用 TBD、TODO、implement later。
- 每个实现任务都给出目标函数、示例代码和验证命令。

**Type consistency:**
- `projectBasics[]` 使用现有字段对象形态：`key`、`label`、`value`、`status`、source evidence。
- `bidderInstructions[]` 使用行记录形态：`clauseNo`、`clauseName`、`content`、source evidence。
- `commercialRejectionClauses[]` 使用行记录形态：`title`、`content`、`matchedKeywords`、`riskLevel`、source evidence。
- `scoringCriteria.business/price/compliance` 保持现有 row 形态，不改字段名。
