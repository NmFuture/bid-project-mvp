# S7 只按素材匹配结果组装 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让技术标 S7 只消费 S4 已选择素材，并由父章节整章素材完全覆盖后代节点。

**Architecture:** S4 gap plan 成为素材选择唯一事实来源。S7 使用无素材的目录骨架与 gap plan 做精确编号映射，不再生成或使用运行期语义匹配卡片；`chapter_master` 的后代节点在计划阶段删除，父素材内部 Heading 决定最终子目录。

**Tech Stack:** Python 3、FastAPI service、python-docx、unittest/pytest

---

### Task 1: 固化 gap plan 权威语义

**Files:**
- Modify: `code/sewpg-bid-backend/tests/test_technical_final_assembly.py`
- Modify: `code/sewpg-bid-backend/opencode/skills/bid-tech-assembler/scripts/build_assembly.py`

- [ ] **Step 1: 写入父章节覆盖和禁止 Wiki 猜测的失败测试**

在 `test_technical_final_assembly.py` 增加用例，构造一个已被 Wiki 猜中五份素材的 `6.6`，以及 gap plan 中选中整章素材的第 6 章：

```python
def test_gap_plan_is_authoritative_and_chapter_master_drops_descendants(self):
    guessed_plan = [
        {"chapter_no_flat": "6", "chapter_no": "第6章", "title": "产品交付、考核及验收", "paths": []},
        {"chapter_no_flat": "6.6", "chapter_no": "6.6", "title": "技术附表", "paths": ["附表B.docx", "附表C.docx", "附表I.docx"]},
    ]
    gap_items = [
        {
            "id": "GAP-PARENT",
            "number": "第6章",
            "title": "产品交付、考核及验收",
            "coverageRole": "chapter_master",
            "matchedMaterials": [{"path": "产品交付.docx"}],
        },
        {
            "id": "GAP-CHILD",
            "number": "6.6",
            "title": "技术附表",
            "coverageRole": "covered_by_parent",
            "coveredByParent": "GAP-PARENT",
            "matchedMaterials": [{"path": "附表I.docx"}],
        },
    ]
    result = build_assembly.apply_gap_plan(guessed_plan, gap_plan_path)
    self.assertEqual([item["chapter_no_flat"] for item in result], ["6"])
    self.assertEqual(result[0]["paths"], ["产品交付.docx"])
```

- [ ] **Step 2: 运行测试并确认红灯**

Run:

```bash
PYTHONPATH=. pytest tests/test_technical_final_assembly.py::TechnicalFinalAssemblyTests::test_gap_plan_is_authoritative_and_chapter_master_drops_descendants -q
```

Expected: FAIL，当前结果仍包含 `6.6`。

- [ ] **Step 3: 最小实现精确映射和后代删除**

在 `build_assembly.py` 中：

```python
def _drop_chapter_master_descendants(plan: list[dict]) -> list[dict]:
    prefixes = {
        str(item.get("chapter_no_flat") or "").strip()
        for item in plan
        if str(item.get("coverage_role") or "") == "chapter_master" and item.get("paths")
    }
    return [
        item
        for item in plan
        if not any(
            str(item.get("chapter_no_flat") or "").startswith(f"{prefix}.")
            for prefix in prefixes
        )
    ]
```

`apply_gap_plan` 只按目录编号关联，不再使用标题归一化回退；先清空每个计划节点已有 `paths`，再写入 gap plan 路径，最后调用 `_drop_chapter_master_descendants`。

- [ ] **Step 4: 验证绿灯**

运行 Task 1 聚焦测试，Expected: PASS。

### Task 2: 保持选中素材与 AI 质量门禁

**Files:**
- Modify: `code/sewpg-bid-backend/tests/test_technical_final_assembly.py`
- Modify: `code/sewpg-bid-backend/opencode/skills/bid-tech-assembler/scripts/build_assembly.py`

- [ ] **Step 1: 写入选中素材优先级失败测试**

新增两个用例：

```python
def test_pending_fill_task_still_uses_selected_material_without_ai_artifact(self):
    item = {
        "fillTasks": [{"status": "pending"}],
        "matchedMaterials": [{"path": "已选素材.docx"}],
        "resolvedArtifacts": [],
    }
    self.assertEqual(build_assembly._gap_plan_paths(item), ["已选素材.docx"])

def test_unreviewed_ai_artifact_does_not_fallback_to_selected_template(self):
    item = {
        "matchedMaterials": [{"path": "原模板.docx"}],
        "resolvedArtifacts": [{"source": "ai_fill", "path": "未通过.docx", "s7Ready": False}],
    }
    self.assertEqual(build_assembly._gap_plan_paths(item), [])
```

- [ ] **Step 2: 运行测试并确认第一条红灯**

Run:

```bash
PYTHONPATH=. pytest tests/test_technical_final_assembly.py -k "pending_fill_task or unreviewed_ai_artifact" -q
```

Expected: 待填写任务用例 FAIL，未通过 AI 用例保持 PASS。

- [ ] **Step 3: 最小修改路径选择规则**

规则固定为：存在任何 `resolvedArtifacts` 时只选择其中通过门禁的产物；不存在任何产物时使用 `matchedMaterials`。`fillTasks` 本身不再屏蔽页面已选素材。

- [ ] **Step 4: 验证两条用例通过**

运行 Task 2 命令，Expected: 2 passed。

### Task 3: S7 禁止无 gap plan 回退

**Files:**
- Modify: `code/sewpg-bid-backend/tests/test_fill_generation.py`
- Modify: `code/sewpg-bid-backend/app/services/tech_assembly.py`
- Modify: `code/sewpg-bid-backend/opencode/skills/bid-tech-assembler/scripts/run_from_manifest.py`

- [ ] **Step 1: 写入 service 失败测试**

新增断言：项目已有 `gap_state.plan` 即使 review 尚未 confirmed，也会复制到 S7 workdir；完全没有计划时抛出 `ValueError("请先完成素材匹配")`。

- [ ] **Step 2: 运行测试并确认红灯**

Run:

```bash
PYTHONPATH=. pytest tests/test_fill_generation.py -k "gap_plan" -q
```

Expected: 未确认计划当前返回 `None`，测试 FAIL。

- [ ] **Step 3: 修改编排入口**

`_prepare_gap_plan` 不再以 review confirmed 作为读取现有匹配计划的条件；保留 AI 产物质量字段。主流程若取不到计划则立即抛错，并删除 `_augment_wiki_with_material_cards(...)` 调用。manifest 中 `gapPlanPath` 必须为非空。

- [ ] **Step 4: 修改 runner 为权威模式**

`run_from_manifest.py` 将 `gapPlanPath` 设为 required，并让 `build_assembly.py` 在 gap plan 模式下以 `build_plan(toc, [], params)` 创建空素材骨架，再应用 gap plan；Wiki 只参与已选文件的物理导出，不参与选择。

- [ ] **Step 5: 验证聚焦测试通过**

运行 Task 3 命令和 `tests/test_technical_final_assembly.py`，Expected: PASS。

### Task 4: 父素材 Heading 决定目录

**Files:**
- Modify: `code/sewpg-bid-backend/tests/test_technical_final_assembly.py`
- Verify: `code/sewpg-bid-backend/opencode/skills/bid-tech-assembler/scripts/merger.py`
- Verify: `code/sewpg-bid-backend/opencode/skills/bid-tech-assembler/scripts/numbering_fixer.py`

- [ ] **Step 1: 扩充现有 chapter_master 回归用例**

在父素材中加入与原 S2 子目录不同的 Heading，断言最终 Word 只出现父素材 Heading，且连续编号；被覆盖的 S2 子目录标题和其独立素材正文均不出现。

- [ ] **Step 2: 运行用例确认当前实现是否满足**

Run:

```bash
PYTHONPATH=. pytest tests/test_technical_final_assembly.py -k "chapter_master" -q
```

Expected: 若现有 merger 已满足则直接 PASS；否则先观察失败点，再只修 Heading 注入边界。

- [ ] **Step 3: 运行聚焦回归**

Run:

```bash
PYTHONPATH=. pytest tests/test_technical_final_assembly.py tests/test_fill_generation.py -q
git diff --check
```

Expected: 测试全部通过，`git diff --check` 无错误。

- [ ] **Step 4: 检查提交边界并提交**

只暂存本计划涉及的生产文件和新增测试；不暂存用户已有的 `tests/test_toc_skill_scripts.py` 改动及其他未跟踪文件。
