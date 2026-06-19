# 商务模板提取 AI 标题裁决与边界防吞并 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `bid-business-template-extractor` 从“脚本窄候选 + AI 只裁候选 + 下一个 accepted 模板定边界”改造为“脚本高召回标题提取 + AI 标题角色裁决 + 所有边界意义标题防吞并”，解决联合体协议书、偏差表、资格审查子表、其他材料、技术资料、分项报价表等漏提和误合并问题。

**Architecture:** 脚本只负责在格式章节内尽量找全疑似标题，并给 AI 提供压缩上下文，不让 Agent 直接读取大体量 `blocks.json`。AI 负责判断标题角色和模板起终点；脚本在保存和 finalize 阶段只做一致性、安全边界和切片校验。边界计算不再只依赖下一个输出模板，而是同时参考 AI 标记的模板起点、父级章节和边界标题。

**Tech Stack:** Python skill scripts, `python-docx`, backend `unittest/pytest`, Opencode skill command flow `btplbound`, existing FastAPI service wrapper.

---

## 核心逻辑

本计划采用三层职责分工：

1. **脚本高召回找标题**
   - 脚本目标是“尽量别漏”，不是“判断是不是模板”。
   - 标题信号包括标题样式、目录级别、heading 级别、加粗、居中、靠左短标题、分页起始、空行分隔、后接表格、常规序号、非常规附件序号、纯序号弱标题。
   - 对“没有加粗、没有居中、没有 heading 样式、只有序号”的恶劣文件，脚本也要在格式章节内保守纳入疑似标题。

2. **AI 判断标题角色**
   - AI 不读取大 JSON 原文，只读脚本整理后的标题清单和小窗口证据。
   - AI 给每个疑似标题定性：正式模板、父级章节、只作为边界、目录项、正文或噪声。
   - `candidate_templates.json` 在语义上升级为“待 AI 裁决的高召回标题清单”，不再表示脚本已认定它们是模板。

3. **脚本按所有边界意义标题防吞并**
   - 输出模板和阻断边界分开处理。
   - 某标题即使不输出模板，只要 AI 认为它开启了新内容段，就必须阻断前一个模板。
   - 模板终点不能跨越下一个正式模板、父级章节或边界标题。

---

## 文件职责

- `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/docx_blocks.py`
  - 负责从 DOCX 提取 block 和样式信号。
  - 本次确认或补齐 heading 样式、outline/目录级别、加粗、居中、分页、页首等结构证据。

- `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/text_rules.py`
  - 负责标题文本的通用规则。
  - 本次新增或调整序号、附件号、表号、短标题、弱标题规则，避免靠业务关键词写死。

- `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/anchor_detector.py`
  - 负责生成高召回疑似标题。
  - 本次将其从“模板候选检测”改造成“疑似标题检测”。

- `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/header_cluster_detector.py`
  - 负责标题簇、父子标题和合成标题补充。
  - 本次保留 synthetic anchor 能力，并让这些标题进入 AI 可见候选。

- `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/pipeline.py`
  - 负责 prepare/finalize 主流程。
  - 本次 prepare 输出高召回标题清单和小窗口证据；finalize 接收 AI 裁决并切片。

- `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/btplbound_workflow.py`
  - 负责 Agent 分批取证、保存裁决、边界批次、finalize 汇总。
  - 本次加入标题角色裁决和边界参考集合，防止模板跨过 AI 标记的边界标题。

- `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/boundary_validator.py`
  - 负责边界合法性校验。
  - 本次增加“不得跨越边界参考标题”的校验。

- `code/sewpg-bid-backend/app/services/business_template_extractor.py`
  - 负责后端给 Agent 的 prompt 和 skill 调用。
  - 本次更新 prompt，明确 Agent 只读 btplbound 压缩证据，不直接读大 JSON。

- `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/SKILL.md`
  - 负责 skill 使用说明。
  - 本次同步“脚本高召回、AI 裁决、边界防吞并”的工作契约。

- `code/sewpg-bid-backend/tests/test_business_template_extractor_skill_script.py`
  - 负责脚本级回归测试。
  - 本次新增高召回标题、AI 角色裁决、边界参考、防吞并和 prompt 契约测试。

---

## Task 1: 为高召回标题提取写失败测试

**Files:**
- Modify: `code/sewpg-bid-backend/tests/test_business_template_extractor_skill_script.py`

- [ ] **Step 1: 新增 DOCX 构造 helper，覆盖人工经验中的标题形态**

在 `test_business_template_extractor_skill_script.py` 的 helper 区域新增函数：

```python
def build_high_recall_heading_docx(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("这里不是模板。")
    doc.add_page_break()
    heading = doc.add_paragraph("第六章 投标文件格式")
    heading.style = "Heading 1"

    p = doc.add_paragraph("1. 投标函")
    p.style = "Heading 2"
    doc.add_paragraph("致：招标人")

    p = doc.add_paragraph("附件1A 法定代表人身份证明")
    p.style = "Heading 2"
    doc.add_paragraph("姓名：")

    p = doc.add_paragraph("附件1B 授权委托书")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in p.runs:
        run.bold = True
    doc.add_paragraph("委托代理人姓名：")

    doc.add_paragraph("4. 联合体协议书（如有）")
    doc.add_paragraph("所有成员单位自愿组成联合体，共同参加投标。")

    doc.add_paragraph("5. 投标保证金（如有）")
    doc.add_paragraph("请提供投标保证金证明材料。")

    doc.add_paragraph("商务和技术偏差表")
    doc.add_table(rows=1, cols=3).rows[0].cells[0].text = "序号"

    doc.add_paragraph("7. 资格审查资料")
    doc.add_paragraph("基本情况表")
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "投标人名称"

    p = doc.add_paragraph("1.1. 近年财务状况")
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "年份"

    doc.add_paragraph("1.2. 近年完成的类似项目情况表")
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "项目名称"

    doc.add_paragraph("正在供货和新承接的项目情况表")
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "项目名称"

    doc.add_paragraph("近年发生的诉讼及仲裁情况")
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "案件名称"

    doc.add_paragraph("7.9. 制造商授权书")
    doc.add_paragraph("制造商授权内容。")

    doc.add_paragraph("8. 其他材料")
    doc.add_paragraph("其他材料正文。")

    doc.add_paragraph("9. 投标设备技术性能指标的详细描述")
    doc.add_paragraph("请详细描述设备技术性能指标。")

    doc.add_paragraph("10. 技术支持资料")
    doc.add_paragraph("请提供技术支持资料。")

    doc.add_paragraph("11. 技术服务和质保期服务计划")
    doc.add_paragraph("请提供技术服务和质保期服务计划。")

    doc.add_paragraph("12. 分项报价表")
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "报价项"

    doc.add_paragraph("3.1.1风机设备的分项报价表")
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "设备名称"
    doc.save(path)
```

- [ ] **Step 2: 写 prepare 高召回测试**

新增测试：

```python
def test_prepare_exposes_high_recall_headings_for_ai_decision(self) -> None:
    source = self.temp_dir / "high-recall-headings.docx"
    output_dir = self.temp_dir / "high-recall-output"
    manifest = self.temp_dir / "high-recall-manifest.json"
    build_high_recall_heading_docx(source)
    write_manifest(manifest, output_dir=output_dir, source=source, stage="prepare")

    completed = run_manifest(manifest)

    self.assertEqual(completed.returncode, 0, completed.stderr)
    candidates = json.loads((output_dir / "DOC-1" / "candidate_templates.json").read_text(encoding="utf-8"))
    texts = [item["text"] for item in candidates]
    expected = [
        "联合体协议书（如有）",
        "投标保证金（如有）",
        "商务和技术偏差表",
        "资格审查资料",
        "基本情况表",
        "近年财务状况",
        "近年完成的类似项目情况表",
        "正在供货和新承接的项目情况表",
        "近年发生的诉讼及仲裁情况",
        "制造商授权书",
        "其他材料",
        "投标设备技术性能指标的详细描述",
        "技术支持资料",
        "技术服务和质保期服务计划",
        "分项报价表",
        "3.1.1风机设备的分项报价表",
    ]
    for title in expected:
        self.assertTrue(any(title in text for text in texts), title)
```

- [ ] **Step 3: 运行测试确认当前失败**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
pytest tests/test_business_template_extractor_skill_script.py::BusinessTemplateExtractorSkillScriptTests::test_prepare_exposes_high_recall_headings_for_ai_decision -q
```

Expected: FAIL，至少缺少 `联合体协议书（如有）`、`商务和技术偏差表`、`其他材料` 或技术资料标题。

---

## Task 2: 将候选提取从“模板猜测”改成“高召回疑似标题”

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/text_rules.py`
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/anchor_detector.py`
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/header_cluster_detector.py`
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/pipeline.py`
- Test: `code/sewpg-bid-backend/tests/test_business_template_extractor_skill_script.py`

- [ ] **Step 1: 在 `text_rules.py` 增加通用标题形态判断**

实现这些方向，不写具体业务标题白名单：

```python
def has_numbering_prefix(text: str) -> bool:
    normalized = clean_text(text)
    compact = compact_text(normalized)
    return bool(
        re.match(r"^\d+(?:\.\d+)*[.、．]?\s*\S+", normalized)
        or re.match(r"^附件\s*\d+[A-Z]?\s*\S+", normalized, re.IGNORECASE)
        or re.match(r"^\d+[A-Z](?:-\d+)?\s*\S+", compact, re.IGNORECASE)
        or re.match(r"^\d+(?:\.\d+)+\S+", compact)
    )


def has_short_heading_shape(text: str) -> bool:
    compact = compact_text(text)
    if not compact or len(compact) > 40:
        return False
    if looks_like_body_sentence(text):
        return False
    return True
```

要求：

- 这些函数只判断形态，不判断是不是模板。
- 不在这里补“联合体协议书”等业务特例。
- `looks_like_body_sentence()` 不能把短标题里的顿号、括号、数字序号全部误判成正文。

- [ ] **Step 2: 调整 `anchor_detector.detect_candidate_anchors()`**

将 `has_template_shape` 的核心逻辑改为高召回：

```python
has_heading_shape = bool(
    block.get("isLikelyHeading")
    or block.get("isCentered")
    or block.get("isPageFirstNonEmpty")
    or block.get("hasPageBreakBefore")
    or "heading_style" in signals
    or has_numbering_prefix(text)
    or has_short_heading_shape(text)
    or _has_near_following_table(blocks, region, int(block["blockId"]))
)
```

实现要求：

- 在第六章格式区域内，短标题 + 后接表格必须进入候选。
- 靠左、未加粗、无 heading 样式但带序号的短行应进入候选。
- heading 样式或目录级别信号应作为强证据。
- 目录页和封面仍要靠 region、正文长度、候选窗口证据交给 AI 进一步拒绝。

- [ ] **Step 3: 将 synthetic anchors 合并进 prepare 候选**

当前 synthetic anchors 只在脚本兜底边界规划中可见。调整 `pipeline.py`，让 prepare 阶段输出的 `candidate_templates.json` 同时包含：

```text
detect_candidate_anchors() 直接命中的标题
header_cluster_detector 能补出的 synthetic structural title
```

实现方式：

- 保持排序按 blockId。
- 同一 blockId 去重。
- 保留 signals，加入能说明来源的信号，例如 `synthetic_structural_title`。
- `candidate_templates.json` 继续保持现有文件名，避免大范围改后端路径。

- [ ] **Step 4: 运行 prepare 高召回测试**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
pytest tests/test_business_template_extractor_skill_script.py::BusinessTemplateExtractorSkillScriptTests::test_prepare_exposes_high_recall_headings_for_ai_decision -q
```

Expected: PASS。

- [ ] **Step 5: 运行现有 prepare/btplbound 基础测试**

Run:

```powershell
pytest tests/test_business_template_extractor_skill_script.py::BusinessTemplateExtractorSkillScriptTests::test_prepare_writes_candidate_artifacts_and_does_not_slice -q
pytest tests/test_business_template_extractor_skill_script.py::BusinessTemplateExtractorSkillScriptTests::test_btplbound_batches_candidate_and_boundary_decisions_then_finalizes -q
```

Expected: PASS。若候选总数变化，更新断言为“包含必要候选且窗口一一对应”，不要断固定数量。

---

## Task 3: 让 AI 裁决标题角色，而不是只有接受/拒绝

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/btplbound_workflow.py`
- Modify: `code/sewpg-bid-backend/app/services/business_template_extractor.py`
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/SKILL.md`
- Test: `code/sewpg-bid-backend/tests/test_business_template_extractor_skill_script.py`

- [ ] **Step 1: 写角色裁决测试**

新增测试，验证 `btplbound candidate-decision` 能保存四类语义：

```python
def test_btplbound_candidate_decision_preserves_heading_roles(self) -> None:
    source = self.temp_dir / "heading-roles.docx"
    output_dir = self.temp_dir / "heading-roles-output"
    manifest = self.temp_dir / "heading-roles-manifest.json"
    build_high_recall_heading_docx(source)
    write_manifest(manifest, output_dir=output_dir, source=source, stage="prepare")
    self.assertEqual(run_manifest(manifest).returncode, 0)

    batch = stdout_json(run_btplbound("candidate-batch", manifest, "next"))
    by_text = {item["text"]: item for item in batch["candidates"]}
    decision_file = self.temp_dir / "heading-role-decision.json"
    decision_file.write_text(
        json.dumps(
            {
                "decisions": [
                    {
                        "candidateId": item["candidateId"],
                        "isTemplateStart": "基本情况表" in item["text"],
                        "headingRole": (
                            "section_container" if "资格审查资料" in item["text"]
                            else "boundary_only" if "其他材料" in item["text"]
                            else "template_start" if "基本情况表" in item["text"]
                            else "reject"
                        ),
                        "rejectReason": "" if ("基本情况表" in item["text"] or "资格审查资料" in item["text"] or "其他材料" in item["text"]) else "不是本测试关注标题",
                        "templateTitle": item["text"],
                        "templateType": "business_template" if "基本情况表" in item["text"] else "",
                        "confidence": 0.86,
                        "reason": "测试标题角色裁决保存",
                        "needsReview": False,
                    }
                    for item in batch["candidates"]
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    saved = stdout_json(run_btplbound("candidate-decision", manifest, 1, decision_file))

    self.assertGreaterEqual(saved["boundaryReferenceCount"], 3)
```

- [ ] **Step 2: 扩展 candidate decision 归一化逻辑**

在 `normalize_candidate_decisions()` 中加入标题角色概念：

```text
template_start: 输出模板，并参与边界参考
section_container: 不输出模板，但参与边界参考
boundary_only: 不输出模板，但参与边界参考
reject: 不输出模板，也不参与边界参考
```

兼容要求：

- 旧 Agent 只返回 `isTemplateStart` 时仍能工作。
- `isTemplateStart=true` 自动视为 `template_start`。
- `isTemplateStart=false` 且没有角色时默认视为 `reject`。

- [ ] **Step 3: 更新候选批次说明和 prompt**

在 `business_template_extractor.py` 和 `SKILL.md` 中明确：

```text
你看到的是高召回疑似标题，不是脚本已确认模板。
请判断每个标题的角色。
不需要读取完整 blocks.json。
只能通过 btplbound candidate-batch 和 boundary-batch 读取压缩证据。
```

同时说明：

```text
父级章节和边界标题不输出 docx，但会阻断前一个模板。
```

- [ ] **Step 4: 运行角色裁决测试**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
pytest tests/test_business_template_extractor_skill_script.py::BusinessTemplateExtractorSkillScriptTests::test_btplbound_candidate_decision_preserves_heading_roles -q
```

Expected: PASS。

---

## Task 4: 用“边界参考集合”替代“下一个 accepted 模板”

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/btplbound_workflow.py`
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/boundary_validator.py`
- Test: `code/sewpg-bid-backend/tests/test_business_template_extractor_skill_script.py`

- [ ] **Step 1: 新增测试 helper，复用 AI 标题角色裁决写入流程**

在 `test_business_template_extractor_skill_script.py` 中新增两个 helper。第一个 helper 用来模拟 AI 对标题角色的裁决：

```python
def write_heading_role_decisions_for_boundary_reference_test(
    temp_dir: Path,
    manifest: Path,
    output_dir: Path,
) -> None:
    candidates = json.loads((output_dir / "DOC-1" / "candidate_templates.json").read_text(encoding="utf-8"))

    def role_for(text: str) -> tuple[bool, str, str]:
        if any(title in text for title in (
            "制造商授权书",
            "投标设备技术性能指标的详细描述",
            "技术支持资料",
            "技术服务和质保期服务计划",
            "分项报价表",
        )):
            return True, "template_start", ""
        if any(title in text for title in (
            "资格审查资料",
        )):
            return False, "section_container", ""
        if any(title in text for title in (
            "其他材料",
        )):
            return False, "boundary_only", ""
        return False, "reject", "非测试关注标题"

    by_id = {item["candidateId"]: item for item in candidates}
    while True:
        status = stdout_json(run_btplbound("status", manifest))
        if status["candidate"]["decided"] == status["candidate"]["total"]:
            break
        batch = stdout_json(run_btplbound("candidate-batch", manifest, "next"))
        decision_path = temp_dir / f"candidate-{batch['batchNo']}.json"
        decisions = []
        for item in batch["candidates"]:
            is_template, heading_role, reject_reason = role_for(item["text"])
            decisions.append(
                {
                    "candidateId": item["candidateId"],
                    "isTemplateStart": is_template,
                    "headingRole": heading_role,
                    "rejectReason": reject_reason,
                    "templateTitle": by_id[item["candidateId"]]["text"],
                    "templateType": "business_template" if is_template else "",
                    "confidence": 0.9,
                    "reason": "测试边界参考集合",
                    "needsReview": False,
                }
            )
        decision_path.write_text(json.dumps({"decisions": decisions}, ensure_ascii=False), encoding="utf-8")
        completed = run_btplbound("candidate-decision", manifest, batch["batchNo"], decision_path)
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)
```

第二个 helper 用来为所有 boundary batch 写入合法边界，便于 finalize 测试复用：

```python
def write_valid_boundary_decisions_for_all_batches(temp_dir: Path, manifest: Path) -> None:
    while True:
        status = stdout_json(run_btplbound("status", manifest))
        if status["boundary"]["decided"] == status["boundary"]["total"]:
            break
        batch = stdout_json(run_btplbound("boundary-batch", manifest, "next"))
        decision_path = temp_dir / f"boundary-{batch['batchNo']}.json"
        decisions = []
        for template in batch["templates"]:
            decisions.append(
                {
                    "candidateId": template["candidateId"],
                    "startBlockId": template["suggestedStartBlockId"],
                    "endBlockId": template["maxEndBlockId"],
                    "confidence": 0.9,
                    "reason": "测试使用最大允许边界，验证不会跨越边界参考标题",
                    "needsReview": False,
                }
            )
        decision_path.write_text(json.dumps({"decisions": decisions}, ensure_ascii=False), encoding="utf-8")
        completed = run_btplbound("boundary-decision", manifest, batch["batchNo"], decision_path)
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)
```

- [ ] **Step 2: 写防吞并失败测试**

新增测试，模拟 AI 认为“其他材料”只作边界、不输出模板：

```python
def test_boundary_batch_uses_boundary_only_heading_to_stop_previous_template(self) -> None:
    source = self.temp_dir / "boundary-reference.docx"
    output_dir = self.temp_dir / "boundary-reference-output"
    manifest = self.temp_dir / "boundary-reference-manifest.json"
    build_high_recall_heading_docx(source)
    write_manifest(manifest, output_dir=output_dir, source=source, stage="prepare")
    self.assertEqual(run_manifest(manifest).returncode, 0)

    all_candidates = json.loads((output_dir / "DOC-1" / "candidate_templates.json").read_text(encoding="utf-8"))
    def candidate_containing(text: str) -> dict:
        return next(item for item in all_candidates if text in item["text"])

    manufacturer = candidate_containing("制造商授权书")
    other = candidate_containing("其他材料")
    commitment = candidate_containing("投标设备技术性能指标的详细描述")

    # 按实际批次逐批写裁决；未关注标题统一 reject。
    while True:
        status = stdout_json(run_btplbound("status", manifest))
        if status["candidate"]["decided"] == status["candidate"]["total"]:
            break
        batch = stdout_json(run_btplbound("candidate-batch", manifest, "next"))
        decision_path = self.temp_dir / f"candidate-{batch['batchNo']}.json"
        decisions = []
        for item in batch["candidates"]:
            is_manufacturer = item["candidateId"] == manufacturer["candidateId"]
            is_other = item["candidateId"] == other["candidateId"]
            is_commitment = item["candidateId"] == commitment["candidateId"]
            decisions.append(
                {
                    "candidateId": item["candidateId"],
                    "isTemplateStart": is_manufacturer or is_commitment,
                    "headingRole": "template_start" if (is_manufacturer or is_commitment) else "boundary_only" if is_other else "reject",
                    "rejectReason": "" if (is_manufacturer or is_commitment or is_other) else "非测试关注标题",
                    "templateTitle": item["text"],
                    "templateType": "business_template" if (is_manufacturer or is_commitment) else "",
                    "confidence": 0.9,
                    "reason": "测试边界参考集合",
                    "needsReview": False,
                }
            )
        decision_path.write_text(json.dumps({"decisions": decisions}, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(run_btplbound("candidate-decision", manifest, batch["batchNo"], decision_path).returncode, 0)

    boundary_batch = stdout_json(run_btplbound("boundary-batch", manifest, "next"))
    manufacturer_template = next(item for item in boundary_batch["templates"] if item["candidateId"] == manufacturer["candidateId"])

    self.assertLess(manufacturer_template["maxEndBlockId"], int(other["candidateBlockId"]))
```

- [ ] **Step 3: 实现边界参考集合**

在 `btplbound_workflow.py` 中增加逻辑：

```text
template_start: 进入 boundary-batch，并作为边界参考
section_container: 不进入 boundary-batch，但作为边界参考
boundary_only: 不进入 boundary-batch，但作为边界参考
reject: 不进入 boundary-batch，也不是边界参考
```

将 `boundary_limits()` 从“找下一个 accepted candidate”改成“找下一个边界参考标题”。

- [ ] **Step 4: 校验边界决策不得跨越参考标题**

在 `normalize_boundary_decisions()` 或 `boundary_validator.py` 中校验：

```text
如果模板 A 与 AI 给出的 endBlockId 之间存在更靠前的 boundary reference，拒绝该边界决策。
```

错误信息包含：

```text
endBlockId must not cross the next boundary reference heading
```

- [ ] **Step 5: 运行防吞并测试**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
pytest tests/test_business_template_extractor_skill_script.py::BusinessTemplateExtractorSkillScriptTests::test_boundary_batch_uses_boundary_only_heading_to_stop_previous_template -q
```

Expected: PASS。

---

## Task 5: 让 boundary-batch 给 AI 看见边界参考，而不是只看模板正文

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/btplbound_workflow.py`
- Test: `code/sewpg-bid-backend/tests/test_business_template_extractor_skill_script.py`

- [ ] **Step 1: 写 boundary evidence 测试**

新增测试：

```python
def test_boundary_batch_includes_next_boundary_reference_summary(self) -> None:
    source = self.temp_dir / "boundary-summary.docx"
    output_dir = self.temp_dir / "boundary-summary-output"
    manifest = self.temp_dir / "boundary-summary-manifest.json"
    build_high_recall_heading_docx(source)
    write_manifest(manifest, output_dir=output_dir, source=source, stage="prepare")
    self.assertEqual(run_manifest(manifest).returncode, 0)

    write_heading_role_decisions_for_boundary_reference_test(self.temp_dir, manifest, output_dir)

    boundary_batch = stdout_json(run_btplbound("boundary-batch", manifest, "next"))
    manufacturer_template = next(item for item in boundary_batch["templates"] if "制造商授权书" in item["templateTitle"])

    self.assertIn("nextBoundaryReference", manufacturer_template)
    self.assertIn("其他材料", manufacturer_template["nextBoundaryReference"]["text"])
```

- [ ] **Step 2: 在 boundary-batch 中加入下一边界摘要**

给每个待裁模板提供：

```text
当前模板标题
当前模板起点
最大允许终点
下一边界参考标题摘要
压缩后的当前模板证据窗口
```

注意：

- 不内联完整 `blocks.json`。
- 证据窗口保持紧凑，避免 Agent 上下文过大。

- [ ] **Step 3: 运行 boundary evidence 测试**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
pytest tests/test_business_template_extractor_skill_script.py::BusinessTemplateExtractorSkillScriptTests::test_boundary_batch_includes_next_boundary_reference_summary -q
```

Expected: PASS。

---

## Task 6: 更新 finalize 对 AI 裁决的兼容和审计输出

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/btplbound_workflow.py`
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/pipeline.py`
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/scripts/report_writer.py`
- Test: `code/sewpg-bid-backend/tests/test_business_template_extractor_skill_script.py`

- [ ] **Step 1: 写 finalize 审计测试**

新增测试：

```python
def test_finalize_reports_boundary_reference_counts(self) -> None:
    source = self.temp_dir / "finalize-boundary-reference.docx"
    output_dir = self.temp_dir / "finalize-boundary-reference-output"
    manifest = self.temp_dir / "finalize-boundary-reference-manifest.json"
    build_high_recall_heading_docx(source)
    write_manifest(manifest, output_dir=output_dir, source=source, stage="prepare")
    self.assertEqual(run_manifest(manifest).returncode, 0)

    write_heading_role_decisions_for_boundary_reference_test(self.temp_dir, manifest, output_dir)
    write_valid_boundary_decisions_for_all_batches(self.temp_dir, manifest)

    final = stdout_json(run_btplbound("finalize", manifest))

    self.assertIn("boundaryReferenceCount", final["summary"])
    self.assertGreater(final["summary"]["boundaryReferenceCount"], final["summary"]["acceptedTemplateCount"])
```

- [ ] **Step 2: finalize 汇总保留角色统计**

`btplbound finalize` 的 summary 增加可审计统计：

```text
headingDecisionCount
acceptedTemplateCount
boundaryReferenceCount
sectionContainerCount
boundaryOnlyCount
rejectedCount
```

这些统计用于排查“AI 看到了但拒绝了”还是“脚本没捞到”。

- [ ] **Step 3: review.md 展示边界参考**

在 `report_writer.py` 输出中增加：

```text
被输出模板
父级章节标题
只作为边界的标题
被拒绝标题
```

目的：以后遇到误合并，可以直接看 AI 是否把中间标题标成边界。

- [ ] **Step 4: 运行 finalize 审计测试**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
pytest tests/test_business_template_extractor_skill_script.py::BusinessTemplateExtractorSkillScriptTests::test_finalize_reports_boundary_reference_counts -q
```

Expected: PASS。

---

## Task 7: 更新后端 prompt，约束 Agent 不读大 JSON

**Files:**
- Modify: `code/sewpg-bid-backend/app/services/business_template_extractor.py`
- Test: `code/sewpg-bid-backend/tests/test_business_template_extractor_skill_script.py`

- [ ] **Step 1: 写 prompt 合同测试**

修改或新增测试：

```python
def test_boundary_decision_prompt_describes_high_recall_heading_role_flow(self) -> None:
    output_dir = self.temp_dir / "prompt-output"
    document_output = output_dir / "DOC-1"
    document_output.mkdir(parents=True)
    (document_output / "candidate_templates.json").write_text("[]", encoding="utf-8")
    (document_output / "candidate_windows.json").write_text("[]", encoding="utf-8")
    (document_output / "blocks.json").write_text("[]", encoding="utf-8")
    (document_output / "regions.json").write_text("[]", encoding="utf-8")
    prepare_payload = {
        "documents": [
            {
                "id": "DOC-1",
                "outputDir": str(document_output),
                "summary": {"candidateCount": 0},
            }
        ]
    }

    prompt = build_business_template_boundary_decision_prompt(
        project_id="proj",
        manifest_path=self.temp_dir / "manifest.json",
        output_dir=output_dir,
        prepare_payload=prepare_payload,
    )

    self.assertIn("高召回疑似标题", prompt)
    self.assertIn("template_start", prompt)
    self.assertIn("boundary_only", prompt)
    self.assertIn("section_container", prompt)
    self.assertIn("不要直接读取完整 blocks.json", prompt)
    self.assertIn("btplbound candidate-batch", prompt)
    self.assertIn("btplbound boundary-batch", prompt)
```

- [ ] **Step 2: 更新 prompt**

在 prompt 中说明：

```text
candidate_templates.json 是高召回疑似标题，不是脚本确认模板。
你必须通过 candidate-batch 对每个标题定角色。
边界阶段只能为 template_start 生成起终点。
section_container 和 boundary_only 不输出模板，但必须作为边界参考。
不要读取完整 blocks.json；如需证据，使用 btplbound 返回的压缩 evidenceBlocks。
```

- [ ] **Step 3: 运行 prompt 测试**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
pytest tests/test_business_template_extractor_skill_script.py::BusinessTemplateExtractorSkillScriptTests::test_boundary_decision_prompt_describes_high_recall_heading_role_flow -q
```

Expected: PASS。

---

## Task 8: 用闻喜型最小样例做端到端回归

**Files:**
- Modify: `code/sewpg-bid-backend/tests/test_business_template_extractor_skill_script.py`

- [ ] **Step 1: 写闻喜型端到端测试**

新增测试使用 `build_high_recall_heading_docx()`，模拟 AI 裁决：

```text
联合体协议书（如有） -> template_start
投标保证金（如有） -> template_start
商务和技术偏差表 -> template_start
资格审查资料 -> section_container
基本情况表 -> template_start
近年财务状况 -> template_start
近年完成的类似项目情况表 -> template_start
正在供货和新承接的项目情况表 -> template_start
近年发生的诉讼及仲裁情况 -> template_start
其他材料 -> boundary_only 或 template_start
投标设备技术性能指标的详细描述 -> template_start
技术支持资料 -> template_start
技术服务和质保期服务计划 -> template_start
分项报价表 -> template_start
3.1.1风机设备的分项报价表 -> template_start
```

测试断言：

```python
titles = [item["title"] for item in payload["appendices"]]
self.assertIn("联合体协议书（如有）", titles)
self.assertIn("投标保证金（如有）", titles)
self.assertIn("商务和技术偏差表", titles)
self.assertIn("基本情况表", titles)
self.assertIn("近年完成的类似项目情况表", titles)
self.assertIn("正在供货和新承接的项目情况表", titles)
self.assertIn("投标设备技术性能指标的详细描述", titles)
self.assertIn("技术支持资料", titles)
self.assertIn("技术服务和质保期服务计划", titles)
self.assertIn("分项报价表", titles)
```

同时断言边界不吞并：

```python
boundaries = json.loads((output_dir / "DOC-1" / "boundaries.json").read_text(encoding="utf-8"))
by_title = {item["title"]: item for item in boundaries["templates"]}
self.assertLess(by_title["制造商授权书"]["endBlockId"], block_id_by_text(blocks, "其他材料"))
self.assertLess(by_title["签订三方协议承诺书"]["endBlockId"], block_id_by_text(blocks, "投标设备技术性能指标的详细描述"))
```

- [ ] **Step 2: 运行端到端测试**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
pytest tests/test_business_template_extractor_skill_script.py::BusinessTemplateExtractorSkillScriptTests::test_wenxi_like_ai_heading_roles_extract_expected_templates_without_merging -q
```

Expected: PASS。

---

## Task 9: 更新 skill 文档和完整回归

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skill/bid-business-template-extractor/SKILL.md`
- Test: `code/sewpg-bid-backend/tests/test_business_template_extractor_skill_script.py`
- Test: `code/sewpg-bid-backend/tests/test_opencode_client.py`
- Test: `code/sewpg-bid-backend/tests/test_parse_pipeline.py`

- [ ] **Step 1: 更新 `SKILL.md`**

写清楚：

```text
prepare 阶段只生成高召回标题和压缩证据，不切片。
Agent 必须先做标题角色裁决。
Agent 只能对 template_start 做模板边界裁决。
section_container 和 boundary_only 不输出模板，但作为边界参考。
finalize 根据 AI 裁决切片，并拒绝跨越边界参考的范围。
```

- [ ] **Step 2: 运行模板提取 skill 全量测试**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
pytest tests/test_business_template_extractor_skill_script.py -q
```

Expected: PASS。

- [ ] **Step 3: 运行 Agent 早停和 parse pipeline 相关测试**

Run:

```powershell
pytest tests/test_opencode_client.py::OpencodeClientTests::test_decide_business_template_boundaries_uses_btplbound_finalize_early_completion -q
pytest tests/test_opencode_client.py::OpencodeClientTests::test_btplbound_non_finalize_commands_do_not_trigger_early_completion -q
pytest tests/test_parse_pipeline.py::ParsePipelineTests::test_business_bid_uses_template_extractor_and_keeps_header_cluster -q
pytest tests/test_parse_pipeline.py::ParsePipelineTests::test_business_template_extractor_appendices_survive_skill_result_merge -q
```

Expected: PASS。

- [ ] **Step 4: 手动复核真实闻喜文件**

使用之前的复现目录或重新创建 manifest：

```powershell
cd C:\Users\99065\Documents\商务标V2
python code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\run_from_manifest.py tmp\wenxi_template_extractor_repro\manifest.prepare.json
```

人工检查：

```text
tmp\wenxi_template_extractor_repro\output\DOC-1\candidate_templates.json
```

必须包含：

```text
联合体协议书（如有）
投标保证金（如有）
商务和技术偏差表
资格审查资料
基本情况表
其他材料
投标设备技术性能指标的详细描述
技术支持资料
技术服务和质保期服务计划
分项报价表
```

再通过 btplbound 模拟 AI 裁决或运行生产 Agent，确认最终 `appendices` 不再发生已知吞并。

---

## 自检清单

- [ ] 高召回标题提取没有依赖“联合体协议书”等业务标题白名单。
- [ ] Agent 不需要读取完整 `blocks.json`。
- [ ] `candidate_templates.json` 语义已从“脚本确认模板”改成“待 AI 裁决疑似标题”。
- [ ] `section_container` 和 `boundary_only` 不输出模板，但能阻断前一个模板。
- [ ] 边界计算不再只看下一个 accepted template。
- [ ] 跨越边界参考标题的 AI endBlockId 会被拒绝。
- [ ] review/finalize 输出能区分“脚本没捞到”和“AI 看到了但拒绝了”。
- [ ] 真实闻喜类问题中的漏提和误合并都有回归覆盖。
