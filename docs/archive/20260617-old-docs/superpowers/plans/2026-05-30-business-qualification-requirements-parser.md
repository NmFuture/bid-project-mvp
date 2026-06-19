# 商务标投标人资格要求解析优化实施计划

> **已废弃 / Superseded:** 本计划中的实现方向仍包含资格章节关键词、排除词和“非资格剔除”脚本规则，容易把语义裁判继续写死在脚本里。后续不得按本计划执行。请改用 `docs/superpowers/plans/2026-05-31-business-s1-ai-semantic-workflow-boundary-plan.md`：脚本只负责候选召回、证据锚定、验真和合成；资格要求、废标项、评分项等最终分类必须由 AI 语义审查层裁判。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将商务标解析页的“投标人资格要求”从关键词捞取改为基于资格章节的结构化抽取，只展示真正的资格条件，并在前端以“序号、要求内容、适用范围、来源”四列可信呈现。

**Architecture:** 只重做 `qualificationRequirements` 的生成和展示契约，不改评分细则、废标项、承诺函等已有模块。后端从 DOCX/文本块中定位资格章节，按条款和标段上下文抽取资格条件，剔除目录、评分、废标、证明材料、纯引用等非资格内容；前端只展示四列，其中“来源”为可读文字，如“招标公告 > 3.2.2 资格能力要求”，不直接展示 `L327` 这类行号。

**Tech Stack:** Python 3、python-docx、pytest/unittest、FastAPI 后端既有解析服务、React 前端既有商务解析页面。

---

## 范围边界

本计划只处理 `structured.fieldGroups.qualificationRequirements`。

不要把被剔除的内容重新塞进评分细则、废标项或资格证明材料模块；这些模块现有效果已经够用，本次只确保“投标人资格要求”不混入其他类型。

前端最终只展示四列：

- 序号
- 要求内容
- 适用范围
- 来源

后端可以保留更多审计字段，但前端主表不要展示过多技术字段。

## 文件结构

- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_contract.py`
  - 新增资格章节候选解析、条款切分、适用范围继承、非资格内容剔除、可读来源生成。
  - 替换 `_build_qualification_requirements(items)` 的调用方式，使其读取 `documents/texts_by_id`，不再只从全局 `items` 关键词捞取。

- Modify: `code/sewpg-bid-backend/app/services/parsing.py`
  - 同步本地兜底解析逻辑，保证 opencode skill 成功或失败时输出契约一致。

- Modify: `code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`
  - 增加 DOCX 端到端测试，覆盖资格章节抽取、适用范围、来源文字、非资格内容剔除。

- Modify: `code/sewpg-bid-backend/tests/test_s1parse_router_script.py`
  - 增加 Markdown/文本入口测试，确保 router 调商务 skill 时也能产生新的资格要求契约。

- Modify: `code/sewpg-bid-frontend/src/workspaces/business/pages/BusinessTenderReview.jsx`
  - 将 `QualificationRequirementsTable` 改为四列。
  - 来源列优先展示后端 `sourceText`/`sourceLabel`，不再直接拼接行号。

---

### Task 1: 写后端失败测试，锁定“资格要求只展示资格条件”

**Files:**
- Modify: `code/sewpg-bid-backend/tests/test_business_parse_skill_script.py`

- [ ] **Step 1: 新增测试用 DOCX 样本构造**

在 `BusinessParseSkillScriptTests` 类中新增测试方法。这个测试必须包含真实混杂场景：资格章节、评分表、废标句、资格证明材料、目录式文字、纯引用句。

```python
    def test_qualification_requirements_are_section_based_and_filtered(self) -> None:
        script_path = self.runner_path()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "资格要求样本.docx"
            doc = Document()
            doc.add_paragraph("目录")
            doc.add_paragraph("3.5 资格审查资料\t23")
            doc.add_paragraph("第一章 招标公告")
            doc.add_paragraph("3. 投标人资格要求")
            doc.add_paragraph("3.1 通用资格条件")
            doc.add_paragraph("3.1.1 投标人为中华人民共和国境内合法注册的独立法人或其他组织，具有独立承担民事责任能力，具有独立订立合同的权利。")
            doc.add_paragraph("3.1.2 投标人没有处于行政主管部门或中国华能集团有限公司系统内单位确认的禁止投标范围和处罚期内。")
            doc.add_paragraph("3.2 专用资格条件")
            doc.add_paragraph("3.2.1 业绩要求：")
            doc.add_paragraph("标段一至标段四（需同时满足）：")
            doc.add_paragraph("（1）投标人须提供近3年有6.25兆瓦或以上容量风电机组通过试运行业绩。")
            doc.add_paragraph("（2）投标人须提供近3年超过100台6.25兆瓦或以上容量等级风电机组合同业绩。")
            doc.add_paragraph("标段五（需同时满足）：")
            doc.add_paragraph("（1）投标人须提供近3年单机容量8兆瓦或以上容量等级海上风电机组通过试运行业绩。")
            doc.add_paragraph("3.2.2 资格能力要求：")
            doc.add_paragraph("标段一至标段四（需同时满足）：")
            doc.add_paragraph("（1）投标人需提供任意6.25兆瓦级别风力发电机组完整型式认证一项。")
            doc.add_paragraph("（2）投标机型已取得对应各项目安全等级要求的设计认证。")
            doc.add_paragraph("标段五（需同时满足）：")
            doc.add_paragraph("（1）投标人需提供任意10兆瓦或以上级别海上风力发电机组完整型式认证一项。")
            doc.add_paragraph("3.2.3 本项目不允许联合体投标。")
            doc.add_paragraph("第二章 投标人须知")
            doc.add_paragraph("1.4 投标人资格要求")
            doc.add_paragraph("1.4.1 投标人应具备承担本招标项目资质条件、能力和信誉：见投标人须知前附表。")
            doc.add_paragraph("3.5 资格审查资料")
            doc.add_paragraph("除投标人须知前附表另有规定外，投标人应按下列规定提供资格审查资料，以证明其满足本章第 1.4 款规定的资质、财务、业绩、信誉等要求。")
            doc.add_paragraph("3.5.1 投标人基本情况表应附营业执照复印件。")
            doc.add_paragraph("第三章 评标办法")
            doc.add_paragraph("附表3：商务评分标准表")
            score_table = doc.add_table(rows=2, cols=4)
            for col, text in enumerate(["序号", "评审因素", "分值", "评审标准"]):
                score_table.cell(0, col).text = text
            for col, text in enumerate(["1", "类似合同业绩", "20", "满足最低资格要求的合同业绩数量者得基础分12分，每增加100台加1分。"]):
                score_table.cell(1, col).text = text
            doc.add_paragraph("投标文件应当对招标文件的实质性要求作出响应，否则投标将被否决。")
            doc.save(source_path)

            output_path = tmp_path / "s1_structured_result.json"
            manifest_path = tmp_path / "s1_parse_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "PRJ-QUAL-SECTION",
                        "bidType": "商务标",
                        "parseProfile": "business",
                        "structuredResultPath": str(output_path),
                        "documents": [
                            {
                                "id": "DOC-QUAL",
                                "name": source_path.name,
                                "sourcePath": str(source_path),
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(script_path), str(manifest_path)],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(json.loads(completed.stdout)["schemaVersion"], "bid-business-tender-structured-v1")
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            rows = payload["structured"]["fieldGroups"]["qualificationRequirements"]
            contents = [row["content"] for row in rows]

            self.assertGreaterEqual(len(rows), 8)
            self.assertTrue(any("合法注册的独立法人" in text for text in contents))
            self.assertTrue(any("6.25兆瓦或以上容量风电机组通过试运行业绩" in text for text in contents))
            self.assertTrue(any("超过100台6.25兆瓦" in text for text in contents))
            self.assertTrue(any("8兆瓦或以上容量等级海上风电机组" in text for text in contents))
            self.assertTrue(any("完整型式认证" in text for text in contents))
            self.assertTrue(any("设计认证" in text for text in contents))
            self.assertTrue(any("不允许联合体投标" in text for text in contents))

            joined = "\n".join(contents)
            self.assertNotIn("满足最低资格要求的合同业绩数量者得基础分", joined)
            self.assertNotIn("资格审查资料\t23", joined)
            self.assertNotIn("营业执照复印件", joined)
            self.assertNotIn("投标将被否决", joined)
            self.assertNotIn("见投标人须知前附表", joined)

            scoped = [row for row in rows if "6.25兆瓦" in row["content"]]
            self.assertTrue(scoped)
            self.assertTrue(all(row["applicableScope"] == "标段一至标段四" for row in scoped))
            offshore = [row for row in rows if "8兆瓦或以上容量等级海上风电机组" in row["content"]]
            self.assertTrue(offshore)
            self.assertEqual(offshore[0]["applicableScope"], "标段五")

            for row in rows:
                self.assertIn("sourceText", row)
                self.assertNotRegex(row["sourceText"], r"^L\d+$")
                self.assertNotRegex(row["sourceText"], r"B\d+/R\d+")
                self.assertTrue(row["sourceText"].startswith("资格要求样本.docx，"))
                self.assertIn("sourceFile", row)
                self.assertIn("section", row)
                self.assertIn("evidence", row)
                self.assertIn("evidenceLocation", row)
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd code/sewpg-bid-backend
python -m pytest tests/test_business_parse_skill_script.py::BusinessParseSkillScriptTests::test_qualification_requirements_are_section_based_and_filtered -q
```

Expected: FAIL。失败原因应包括缺少 `applicableScope`、缺少 `sourceText`、评分/目录/证明材料混入，或未抽到资格章节正文。

- [ ] **Step 3: 暂不提交**

本任务只建立失败测试，等 Task 2 实现后一起提交。

---

### Task 2: 在 Skill 中实现资格章节解析与非资格剔除

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_contract.py`

- [ ] **Step 1: 新增资格解析辅助常量**

在 `COMMITMENT_REQUIREMENT_FIELDS` 后面新增：

```python
QUALIFICATION_SECTION_ANCHORS = (
    "投标人资格要求",
    "投标人资格条件",
    "资格能力要求",
    "专用资格条件",
    "通用资格条件",
    "合格投标人资格",
    "供应商资格要求",
    "资质条件、能力和信誉",
)

QUALIFICATION_STOP_ANCHORS = (
    "投标文件的组成",
    "投标报价",
    "投标保证金",
    "资格审查资料",
    "评标办法",
    "符合性审查",
    "商务评分",
    "技术评分",
    "投标文件格式",
    "合同条款",
)

QUALIFICATION_EXCLUDE_KEYWORDS = (
    "资格审查资料",
    "证明材料",
    "复印件",
    "扫描件",
    "附件",
    "评分",
    "得分",
    "分值",
    "满分",
    "基础分",
    "加分",
    "否决",
    "废标",
    "不予受理",
    "目录",
    "页码",
    "见投标人须知前附表",
    "见评标办法前附表",
    "同招标公告",
)

QUALIFICATION_REQUIRED_CUES = (
    "投标人",
    "投标机型",
    "供应商",
    "联合体",
    "须",
    "应",
    "需",
    "具有",
    "具备",
    "不得",
    "不允许",
    "不接受",
    "没有处于",
    "未被",
)

SCOPE_PATTERN = re.compile(r"^(标段[一二三四五六七八九十、至和及\d\\-]+|第[一二三四五六七八九十\\d]+标段|所有标段|全部标段|本项目)(?:（[^）]*）)?[:：]?$")
CLAUSE_PATTERN = re.compile(r"^(?:\\d+(?:\\.\\d+){1,4}|[（(][一二三四五六七八九十\\d]+[）)]|[一二三四五六七八九十\\d]+[、.．])\\s*")
```

- [ ] **Step 2: 新增可读来源生成函数**

在 `_copy_meta_fields` 后新增：

```python
def _qualification_source_text(*, source_file: str, section: str, clause_no: str = "") -> str:
    parts = [part.strip(" ：:") for part in (section, clause_no) if str(part or "").strip()]
    readable = " > ".join(dict.fromkeys(parts))
    if readable:
        return f"{source_file}，{readable}"
    return source_file
```

注意：`sourceText` 不包含 `L327` 或 `B311/R29`。行号保留在 `evidenceLocation`，仅用于审计，不作为前端主表来源文字。

- [ ] **Step 3: 新增文本块读取函数**

在 `_extract_docx_core_candidate_items` 前新增：

```python
def _document_text_lines(document: dict[str, Any], texts_by_id: dict[str, str]) -> list[dict[str, Any]]:
    document_id = str(document.get("id") or "")
    source_file = str(document.get("name") or document_id or "招标文件")
    text = str(texts_by_id.get(document_id) or "")
    lines: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = _clean(raw_line)
        if not line:
            continue
        lines.append(
            {
                "text": line,
                "sourceFile": source_file,
                "sourceDocumentId": document_id,
                "evidenceLocation": f"L{line_number}",
            }
        )
    return lines
```

- [ ] **Step 4: 新增章节状态判断函数**

在 Step 3 后新增：

```python
def _qualification_heading_level(text: str) -> int:
    stripped = str(text or "").strip()
    match = re.match(r"^(\\d+(?:\\.\\d+){0,4})\\s+", stripped)
    if not match:
        return 99
    return match.group(1).count(".") + 1


def _is_qualification_anchor(text: str) -> bool:
    return any(anchor in text for anchor in QUALIFICATION_SECTION_ANCHORS)


def _is_qualification_stop(text: str, active_root_level: int) -> bool:
    if not text:
        return False
    level = _qualification_heading_level(text)
    if level <= active_root_level and not _is_qualification_anchor(text):
        return True
    return any(anchor in text for anchor in QUALIFICATION_STOP_ANCHORS)
```

- [ ] **Step 5: 新增候选条款清洗和过滤函数**

在 Step 4 后新增：

```python
def _normalize_qualification_content(text: str) -> str:
    value = _clean(text)
    value = re.sub(r"^\\d+(?:\\.\\d+){1,4}\\s*", "", value)
    value = re.sub(r"^[（(][一二三四五六七八九十\\d]+[）)]\\s*", "", value)
    value = value.strip(" ：:；;")
    return value


def _looks_like_scope_heading(text: str) -> bool:
    return bool(SCOPE_PATTERN.match(str(text or "").strip()))


def _looks_like_qualification_requirement(text: str) -> bool:
    value = _normalize_qualification_content(text)
    if len(value) < 8:
        return False
    if _looks_like_scope_heading(value):
        return False
    compact = re.sub(r"\\s+", "", value)
    if re.search(r"\\t\\d+$|\\.\\.\\.+\\d+$", value):
        return False
    if any(keyword in value for keyword in QUALIFICATION_EXCLUDE_KEYWORDS):
        return False
    if value in {"见评标办法前附表", "见投标人须知前附表", "同招标公告"}:
        return False
    return any(cue in value for cue in QUALIFICATION_REQUIRED_CUES)
```

- [ ] **Step 6: 新增资格章节抽取函数**

在 Step 5 后新增：

```python
def _extract_qualification_requirements_from_documents(
    documents: list[dict[str, Any]],
    texts_by_id: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for document in documents:
        source_file = str(document.get("name") or document.get("id") or "招标文件")
        document_id = str(document.get("id") or "")
        active = False
        active_root_level = 99
        section_path: list[tuple[int, str]] = []
        applicable_scope = "全部标段"

        for line in _document_text_lines(document, texts_by_id):
            text = str(line["text"])
            level = _qualification_heading_level(text)

            if _is_qualification_anchor(text):
                active = True
                active_root_level = min(active_root_level, level)
                section_path = [(level, text)]
                applicable_scope = "全部标段"
                continue

            if not active:
                continue

            if _is_qualification_stop(text, active_root_level):
                active = False
                section_path = []
                applicable_scope = "全部标段"
                continue

            if level < 99:
                section_path = [(old_level, title) for old_level, title in section_path if old_level < level]
                section_path.append((level, text))

            if _looks_like_scope_heading(text):
                applicable_scope = text.split("（", 1)[0].strip(" ：:")
                continue

            if not _looks_like_qualification_requirement(text):
                continue

            content = _normalize_qualification_content(text)
            section = " > ".join(title for _, title in section_path) or "投标人资格要求"
            clause_no_match = re.match(r"^(\\d+(?:\\.\\d+){1,4}|[（(][一二三四五六七八九十\\d]+[）)])", text)
            clause_no = clause_no_match.group(1) if clause_no_match else ""
            dedupe_key = (content, applicable_scope, section)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            rows.append(
                {
                    "id": f"QUAL-{len(rows) + 1:04d}",
                    "order": len(rows) + 1,
                    "content": content,
                    "applicableScope": applicable_scope or "全部标段",
                    "sourceText": _qualification_source_text(
                        source_file=source_file,
                        section=section,
                        clause_no=clause_no,
                    ),
                    "sourceFile": source_file,
                    "sourceDocumentId": document_id,
                    "section": section,
                    "evidence": text,
                    "evidenceLocation": str(line.get("evidenceLocation") or ""),
                    "confidence": 0.9,
                }
            )

    return rows
```

- [ ] **Step 7: 替换原 `_build_qualification_requirements`**

把原函数替换为兼容兜底版本：

```python
def _build_qualification_requirements(
    items: list[dict[str, Any]],
    *,
    documents: list[dict[str, Any]] | None = None,
    texts_by_id: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if documents is not None and texts_by_id is not None:
        rows = _extract_qualification_requirements_from_documents(documents, texts_by_id)
        if rows:
            return rows

    keywords = ("投标人资格要求", "资格要求", "资格能力要求", "投标人资质条件", "合格投标人")
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        text = " ".join(str(item.get(key) or "") for key in ("title", "keyEntity", "value", "evidence", "section"))
        if not any(keyword in text for keyword in keywords):
            continue
        content = str(item.get("evidence") or item.get("value") or "").strip()
        if not _looks_like_qualification_requirement(content):
            continue
        content = _normalize_qualification_content(content)
        if not content or content in seen:
            continue
        seen.add(content)
        source_file = str(item.get("sourceFile") or "招标文件")
        section = str(item.get("section") or item.get("title") or "投标人资格要求")
        matched.append(
            {
                "id": f"QUAL-{len(matched) + 1:04d}",
                "order": len(matched) + 1,
                "content": content,
                "applicableScope": "全部标段",
                "sourceText": _qualification_source_text(source_file=source_file, section=section),
                **_copy_meta_fields(item),
                "confidence": float(item.get("confidence") or 0.72),
            }
        )
    return matched
```

- [ ] **Step 8: 更新 `build_business_result` 调用**

在 `build_business_result` 中把：

```python
"qualificationRequirements": _build_qualification_requirements(merged_items),
```

改为：

```python
"qualificationRequirements": _build_qualification_requirements(
    merged_items,
    documents=documents,
    texts_by_id=texts_by_id,
),
```

- [ ] **Step 9: 运行 Task 1 的失败测试**

Run:

```bash
cd code/sewpg-bid-backend
python -m pytest tests/test_business_parse_skill_script.py::BusinessParseSkillScriptTests::test_qualification_requirements_are_section_based_and_filtered -q
```

Expected: PASS。

- [ ] **Step 10: 运行商务 skill 既有测试**

Run:

```bash
cd code/sewpg-bid-backend
python -m pytest tests/test_business_parse_skill_script.py -q
```

Expected: PASS。

- [ ] **Step 11: 提交后端 skill 变化**

```bash
git add code/sewpg-bid-backend/opencode/skill/bid-business-tender-structured-parser/scripts/business_contract.py code/sewpg-bid-backend/tests/test_business_parse_skill_script.py
git commit -m "fix: parse business qualification requirements from sections"
```

---

### Task 3: 同步本地兜底解析逻辑

**Files:**
- Modify: `code/sewpg-bid-backend/app/services/parsing.py`

- [ ] **Step 1: 将 Task 2 的资格解析辅助逻辑同步到 `parsing.py`**

在 `parsing.py` 中找到已有的商务解析辅助函数区域，把 Task 2 新增的常量和函数同步进去。保持函数名一致：

```python
QUALIFICATION_SECTION_ANCHORS = (...)
QUALIFICATION_STOP_ANCHORS = (...)
QUALIFICATION_EXCLUDE_KEYWORDS = (...)
QUALIFICATION_REQUIRED_CUES = (...)
SCOPE_PATTERN = re.compile(...)
CLAUSE_PATTERN = re.compile(...)
def _qualification_source_text(...): ...
def _document_text_lines(...): ...
def _qualification_heading_level(...): ...
def _is_qualification_anchor(...): ...
def _is_qualification_stop(...): ...
def _normalize_qualification_content(...): ...
def _looks_like_scope_heading(...): ...
def _looks_like_qualification_requirement(...): ...
def _extract_qualification_requirements_from_documents(...): ...
```

如果文件里已有同名或近似函数，优先复用并补齐行为，不要制造两套不同规则。

- [ ] **Step 2: 替换本地 `_build_qualification_requirements`**

在 `parsing.py` 中找到 `_build_qualification_requirements`，按 Task 2 Step 7 的签名和行为同步。

- [ ] **Step 3: 更新 `_transform_to_business_contract` 调用**

把：

```python
"qualificationRequirements": _build_qualification_requirements(merged_items),
```

改为：

```python
"qualificationRequirements": _build_qualification_requirements(
    merged_items,
    documents=documents,
    texts_by_id=texts_by_id,
),
```

- [ ] **Step 4: 运行解析管线测试**

Run:

```bash
cd code/sewpg-bid-backend
python -m pytest tests/test_parse_pipeline.py tests/test_s1parse_router_script.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交本地兜底同步**

```bash
git add code/sewpg-bid-backend/app/services/parsing.py
git commit -m "fix: align local business qualification parsing"
```

---

### Task 4: 补 Router 文本入口测试，保证 Markdown/纯文本也泛化

**Files:**
- Modify: `code/sewpg-bid-backend/tests/test_s1parse_router_script.py`

- [ ] **Step 1: 新增 router 资格要求测试**

在 `S1ParseRouterScriptTests` 中新增：

```python
    def test_business_router_outputs_readable_qualification_requirements(self) -> None:
        router_path = self.router_path()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "商务资格要求.md"
            source_path.write_text(
                "\n".join(
                    [
                        "# 商务招标文件",
                        "第一章 招标公告",
                        "3. 投标人资格要求",
                        "3.1 通用资格条件",
                        "3.1.1 投标人为中华人民共和国境内合法注册的独立法人或其他组织。",
                        "3.2 专用资格条件",
                        "3.2.1 业绩要求：",
                        "标段一（需同时满足）：",
                        "（1）投标人须提供近3年同类项目合同业绩。",
                        "3.2.2 本项目不接受联合体投标。",
                        "第三章 评标办法",
                        "满足最低资格要求的合同业绩数量者得基础分12分。",
                        "3.5 资格审查资料\t23",
                    ]
                ),
                encoding="utf-8",
            )
            output_path = tmp_path / "s1_structured_result.json"
            manifest_path = tmp_path / "s1_parse_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "PRJ-BUSINESS-QUAL-ROUTER",
                        "bidType": "商务标",
                        "parseProfile": "business",
                        "structuredResultPath": str(output_path),
                        "documents": [
                            {
                                "id": "DOC-1",
                                "name": source_path.name,
                                "sourcePath": str(source_path),
                                "textPath": str(source_path),
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(router_path), str(manifest_path)],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(json.loads(completed.stdout)["schemaVersion"], "bid-business-tender-structured-v1")
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            rows = payload["structured"]["fieldGroups"]["qualificationRequirements"]
            contents = "\n".join(row["content"] for row in rows)
            self.assertIn("中华人民共和国境内合法注册", contents)
            self.assertIn("近3年同类项目合同业绩", contents)
            self.assertIn("不接受联合体投标", contents)
            self.assertNotIn("基础分12分", contents)
            self.assertNotIn("资格审查资料\t23", contents)
            self.assertTrue(any(row["applicableScope"] == "标段一" for row in rows))
            self.assertTrue(all("sourceText" in row and "L" not in row["sourceText"] for row in rows))
```

- [ ] **Step 2: 运行新增测试**

Run:

```bash
cd code/sewpg-bid-backend
python -m pytest tests/test_s1parse_router_script.py::S1ParseRouterScriptTests::test_business_router_outputs_readable_qualification_requirements -q
```

Expected: PASS。

- [ ] **Step 3: 运行 router 全量测试**

Run:

```bash
cd code/sewpg-bid-backend
python -m pytest tests/test_s1parse_router_script.py -q
```

Expected: PASS。

- [ ] **Step 4: 提交 router 测试**

```bash
git add code/sewpg-bid-backend/tests/test_s1parse_router_script.py
git commit -m "test: cover readable business qualification sources"
```

---

### Task 5: 前端四列表格展示

**Files:**
- Modify: `code/sewpg-bid-frontend/src/workspaces/business/pages/BusinessTenderReview.jsx`

- [ ] **Step 1: 新增资格来源格式化函数**

在 `sourceValue` 后新增：

```jsx
const qualificationSourceValue = (row = {}) => {
  const readable = displayValue(row.sourceText || row.sourceLabel || row.source)
  if (readable !== '-') return readable
  return displayValue([row.sourceFile, row.section].filter(Boolean))
}
```

- [ ] **Step 2: 修改 `QualificationRequirementsTable` 为四列**

将该组件的 `table`、`colgroup`、`thead`、`tbody` 改成：

```jsx
function QualificationRequirementsTable({ title, rows = [] }) {
  return (
    <div className="border border-surface-container-high rounded-md overflow-hidden bg-white">
      <div className="px-4 py-3 border-b border-surface-container-high bg-surface-container-low flex items-center justify-between">
        <h4 className="text-sm font-semibold text-on-surface">{title}</h4>
        <span className="text-xs text-outline">{rows.length} 条</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full table-fixed text-sm min-w-[920px]">
          <colgroup>
            <col className="w-20" />
            <col className="w-[34rem]" />
            <col className="w-40" />
            <col className="w-72" />
          </colgroup>
          <thead>
            <tr className="border-b border-surface-container-high">
              <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">序号</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">要求内容</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">适用范围</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">来源</th>
            </tr>
          </thead>
          <tbody>
            {rows.length ? rows.map((row, index) => (
              <tr key={row.id || `qualification-${index}`} className="border-b border-surface-container-high last:border-b-0">
                <td className="px-4 py-2 text-center text-on-surface-variant whitespace-nowrap">{row.order || index + 1}</td>
                <td className="business-core-text-cell px-4 py-2 text-on-surface">
                  {displayValue(row.content || row.value || row.evidence)}
                </td>
                <td className="business-core-text-cell px-4 py-2 text-center text-on-surface-variant">
                  {displayValue(row.applicableScope, '全部标段')}
                </td>
                <td className="business-core-text-cell px-4 py-2 text-on-surface-variant">
                  {qualificationSourceValue(row)}
                </td>
              </tr>
            )) : (
              <tr>
                <td className="px-4 py-3 text-outline" colSpan={4}>未识别到投标人资格要求。</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: 检查没有其他资格表格旧列残留**

Run:

```bash
cd code/sewpg-bid-frontend
rg -n "QualificationRequirementsTable|applicableScope|qualificationSourceValue|未识别到投标人资格要求" src/workspaces/business/pages/BusinessTenderReview.jsx
```

Expected: 能看到 `qualificationSourceValue`、`applicableScope`、`colSpan={4}`。

- [ ] **Step 4: 运行前端构建或静态检查**

Run:

```bash
cd code/sewpg-bid-frontend
npm run build
```

Expected: PASS。

- [ ] **Step 5: 提交前端展示变化**

```bash
git add code/sewpg-bid-frontend/src/workspaces/business/pages/BusinessTenderReview.jsx
git commit -m "fix: show readable business qualification sources"
```

---

### Task 6: 用真实样本回归验证

**Files:**
- No code changes expected.

- [ ] **Step 1: 重新解析真实样本或运行当前样本脚本**

如果容器正在运行，优先通过页面或 API 对 `华能赤峰市翁牛特旗等6个风电项目招标文件.docx` 重新执行商务解析。

如果只做本地脚本验证，可在后端目录运行已有测试，并用真实样本 manifest 复跑 skill。执行 agent 需要根据当前项目实际 `s1_parse_manifest.json` 路径选择命令。

- [ ] **Step 2: 检查后端 JSON**

检查 `structured.fieldGroups.qualificationRequirements`：

```bash
docker exec sewpg_bid_fastapi python - <<'PY'
import json
p='/data/parsed/PRJ-0002/s1_structured_result.json'
d=json.load(open(p,encoding='utf-8'))
rows=d['structured']['fieldGroups']['qualificationRequirements']
for i,row in enumerate(rows,1):
    print(i, row.get('content'), '|', row.get('applicableScope'), '|', row.get('sourceText'))
PY
```

Expected:

- 不再出现 `和湍流的安全等级要求）` 这种残片。
- 不再出现 `√无 □有，具体要求`。
- 不再出现 `资格审查资料\t23`。
- 不再出现 `满足最低资格要求的合同业绩数量者得基础分`。
- 应出现 `3.1 通用资格条件`、`3.2.1 业绩要求`、`3.2.2 资格能力要求`、`不允许联合体投标` 相关内容。
- `sourceText` 是中文可读来源，例如 `华能赤峰市翁牛特旗等6个风电项目招标文件.docx，3. 投标人资格要求 > 3.2.2 资格能力要求`，不是行号。

- [ ] **Step 3: 浏览器人工验收**

打开：

```text
http://localhost/parse/business
```

Expected:

- “二、投标人资格要求”表格为四列：序号、要求内容、适用范围、来源。
- 来源列是可读文字，不是 `L327` 或 `B311/R29`。
- 表格内容像投标人能理解的资格条件，不混入评分、废标、目录或证明材料说明。

- [ ] **Step 4: 运行最终回归**

Run:

```bash
cd code/sewpg-bid-backend
python -m pytest tests/test_business_parse_skill_script.py tests/test_s1parse_router_script.py tests/test_parse_pipeline.py -q
cd ../sewpg-bid-frontend
npm run build
```

Expected: 全部 PASS。

- [ ] **Step 5: 最终提交**

如果 Task 6 没有代码变化，不需要提交。若为真实样本验证临时生成了不该入库的文件，不要提交；只提交代码和测试。

---

## 自检清单

- [ ] `qualificationRequirements` 只包含资格条件。
- [ ] 评分、废标、证明材料、目录、章节标题、纯引用句没有进入资格要求主表。
- [ ] `applicableScope` 对“标段一至标段四”“标段五”等范围继承正确。
- [ ] `sourceText` 是前端可读文字，不直接展示行号或块号。
- [ ] 前端只展示四列。
- [ ] opencode skill 与本地兜底解析输出契约一致。
- [ ] 真实样本页面不再出现当前截图中的第 1、5、7、9、10、12 类错误。
