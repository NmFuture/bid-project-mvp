# 商务目录 Required Status 证据契约 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `bid-business-outline-generator` 中“历史项保留”被误判成“当前项目必要”的根因，把 `action=keep` 与 `required_status=必要` 彻底拆开。

**Architecture:** `opencode` 继续负责语义选择、保留/延后判断和 `required_status` 判断；`outline_authoring_helper.py` 只做机械写回和证据状态契约校验。召回策略不削弱，强证据仍可支撑“必要”，但 `history_fallback + fallback` 不能再被写成“必要”。

**Tech Stack:** Python 3、opencode skill Markdown 指令、`unittest`、现有商务目录生成 JSON 产物、离线 PRJ-0015 样本验收。

---

## 背景判断

当前根因不是 `source_text` 检索不足，而是 `required_status` 规则把两个概念混在了一起：

- `action=keep`：目录节点暂时保留在目录树里，主要表示继承历史结构或当前阶段不删除。
- `required_status=必要`：当前招标文件有足够证据证明该节点必须作为当前项目提交项。

现有 `SKILL.md` 中这句规则有歧义：

```markdown
- “必要”：当前招标文件明确要求提交，或历史目录项已被当前招标文件明确/宽泛要求证明应纳入。
```

这会让 opencode 把“宽泛条款支持保留历史结构”误读为“历史子项都必要”。本次修复只画清状态边界，不新增固定商务标题清单，不针对 PRJ-0015 写死规则，不把 helper 改成语义判断器。

---

## 文件职责

- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\SKILL.md`
  - 删除“明确/宽泛要求证明应纳入”的歧义规则。
  - 增加 `action` 与 `required_status` 的概念拆分。
  - 增加证据范围/强度状态矩阵。
  - 增加 4/5 级历史深层项判断规则。
  - 明确 helper 会拒绝证据状态契约矛盾。
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\outline_authoring_helper.py`
  - 增加非业务硬编码契约校验。
  - 拒绝 `evidence_scope == "history_fallback"` 且 `evidence_strength == "fallback"` 且 `required_status == "必要"`。
  - 不判断标题语义，不修改 opencode 给出的状态，不自动降级为“待确认”。
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_outline_authoring_helper.py`
  - 覆盖 fallback 证据不能写成“必要”。
  - 覆盖 fallback 证据写成“待确认”仍允许。
  - 覆盖强证据写成“必要”仍允许。
- Optional validation artifact only: `C:\Users\99065\Documents\商务标V2\tmp\business_outline_compare\...`
  - 仅用于 PRJ-0015 离线验收输出，不作为线上门禁或提交文件。

---

## Task 1: 先写 helper 契约失败测试

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_outline_authoring_helper.py`

- [ ] **Step 1: 增加失败测试，证明 fallback 证据不能判“必要”**

在 `OutlineAuthoringHelperTest` 中新增测试：

```python
def test_rejects_history_fallback_required_as_necessary(self):
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        history_path, candidates_path, decisions_path, output_path = self._write_inputs(
            tmpdir,
            history_candidates=[
                {
                    "candidate_id": "hist-cand-001",
                    "number": "1.1.1.1",
                    "level": 4,
                    "title_hint": "Historical Detail",
                    "source_text": "1.1.1.1 Historical Detail",
                }
            ],
            source_items=[
                {
                    "id": "BIZ-FALLBACK-0001",
                    "candidate_source_id": "hist-cand-001",
                    "title": "Historical Detail",
                    "candidates": [
                        {
                            "candidate_id": "cand-001",
                            "source_text": "1.1.1.1 Historical Detail",
                            "scope": "history_fallback",
                            "evidence_strength": "fallback",
                            "evidence_category": "material_proof",
                            "match_reason": "history fallback only",
                        }
                    ],
                }
            ],
            decisions={
                "sections": [
                    {
                        "id": "BIZ-FALLBACK-0001",
                        "action": "keep",
                        "required_status": "必要",
                        "reason": "opencode incorrectly treated keep as necessary",
                    }
                ]
            },
        )

        with self.assertRaisesRegex(ValueError, "history_fallback/fallback.*必要"):
            helper.write_outline(
                history_path=history_path,
                source_candidates_path=candidates_path,
                decisions_path=decisions_path,
                output_path=output_path,
            )
```

- [ ] **Step 2: 运行单测确认当前失败**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest opencode.skill.bid-business-outline-generator.scripts.test_outline_authoring_helper -v
```

如果模块路径因目录名含 `-` 无法直接导入，使用已验证的 discover 命令：

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest discover -s opencode/skill/bid-business-outline-generator/scripts -p "test_outline_authoring_helper.py" -v
```

Expected:

- 新测试应失败，因为当前 helper 只校验状态枚举，不拒绝 `history_fallback + fallback + 必要`。

---

## Task 2: 实现 helper 证据状态契约

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\outline_authoring_helper.py`

- [ ] **Step 1: 增加纯契约校验函数**

在 `build_section` 附近新增函数：

```python
def validate_evidence_status_contract(item_id: str, selected: dict[str, Any], required_status: str) -> None:
    evidence_scope = str(selected.get("scope") or "history_fallback").strip()
    evidence_strength = str(selected.get("evidence_strength") or "fallback").strip()
    if (
        evidence_scope == "history_fallback"
        and evidence_strength == "fallback"
        and required_status == "必要"
    ):
        raise ValueError(
            f"{item_id}: history_fallback/fallback evidence cannot be marked 必要; "
            "rewrite the opencode decision as 待确认 or select current tender evidence"
        )
```

- [ ] **Step 2: 在 `build_section` 里调用**

在 `required_status` 枚举校验之后、写 section 字段之前调用：

```python
validate_evidence_status_contract(item_id, selected, required_status)
```

- [ ] **Step 3: 确认 helper 没有做语义判断**

检查实现中不得出现以下内容：

- 固定商务标题清单。
- PRJ-0015 标题或项目编号。
- 对 `action=keep` 的语义重写。
- 把 `required_status` 自动从“必要”改成“待确认”。

Expected:

- helper 只拒绝矛盾决策并要求 opencode 重写，不替 opencode 作最终状态判断。

---

## Task 3: 补充 helper 正向契约测试

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_outline_authoring_helper.py`

- [ ] **Step 1: 增加 fallback 写“待确认”允许测试**

新增测试：

```python
def test_allows_history_fallback_when_status_is_pending(self):
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        history_path, candidates_path, decisions_path, output_path = self._write_inputs(
            tmpdir,
            history_candidates=[
                {
                    "candidate_id": "hist-cand-001",
                    "number": "1.1.1.1",
                    "level": 4,
                    "title_hint": "Historical Detail",
                    "source_text": "1.1.1.1 Historical Detail",
                }
            ],
            source_items=[
                {
                    "id": "BIZ-FALLBACK-0001",
                    "candidate_source_id": "hist-cand-001",
                    "title": "Historical Detail",
                    "candidates": [
                        {
                            "candidate_id": "cand-001",
                            "source_text": "1.1.1.1 Historical Detail",
                            "scope": "history_fallback",
                            "evidence_strength": "fallback",
                            "evidence_category": "material_proof",
                            "match_reason": "history fallback only",
                        }
                    ],
                }
            ],
            decisions={
                "sections": [
                    {
                        "id": "BIZ-FALLBACK-0001",
                        "action": "keep",
                        "required_status": "待确认",
                        "reason": "keep historical structure, current tender evidence is insufficient",
                    }
                ]
            },
        )

        helper.write_outline(
            history_path=history_path,
            source_candidates_path=candidates_path,
            decisions_path=decisions_path,
            output_path=output_path,
        )

        section = json.loads(output_path.read_text(encoding="utf-8"))["sections"][0]
        self.assertEqual(section["required_status"], "待确认")
        self.assertEqual(section["evidence_scope"], "history_fallback")
        self.assertEqual(section["evidence_strength"], "fallback")
```

- [ ] **Step 2: 复用既有强证据测试**

确认现有 `test_strong_candidate_is_not_written_as_history_fallback` 仍然使用：

```python
"scope": "format_area",
"evidence_strength": "strong",
"required_status": "必要",
```

Expected:

- 强证据仍可判“必要”。
- fallback 证据可保留进目录树，但只能是“待确认”或“可选”，不能是“必要”。

- [ ] **Step 3: 运行 helper 单测**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest discover -s opencode/skill/bid-business-outline-generator/scripts -p "test_outline_authoring_helper.py" -v
```

Expected:

- `test_rejects_history_fallback_required_as_necessary` 通过。
- 既有 ID 追踪、defer、strong evidence 测试继续通过。

---

## Task 4: 修改 `SKILL.md` 状态规则

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\SKILL.md`

- [ ] **Step 1: 删除歧义规则**

删除或替换这一句：

```markdown
- “必要”：当前招标文件明确要求提交，或历史目录项已被当前招标文件明确/宽泛要求证明应纳入。
```

- [ ] **Step 2: 写入概念拆分**

在 `required_status` 判断规则前加入：

```markdown
先拆开两个概念：

- `action=keep`：该目录节点暂时保留在目录树里，可能来自历史结构继承、当前招标文件宽泛覆盖、或当前阶段无法确认删除。
- `required_status=必要`：当前招标文件有足够证据证明该节点必须作为当前项目提交项。

`action=keep` 不推出 `required_status=必要`。历史项可以被保留，但如果当前招标文件证据不足，状态必须是“待确认”或在明确条件场景下为“可选”。
```

- [ ] **Step 3: 写入新的状态规则**

替换为：

```markdown
`required_status` 判断规则：

- “必要”：只有当前招标文件有明确提交、格式、资格、评分、组成或实质性响应证据时，才可判定。
- “可选”：仅在当前招标文件明确限定特定条件下提交时使用，例如联合体、代理商、备选方案等情形。
- “待确认”：目录项已有依据进入目录树，但当前招标文件证据不足以证明它必须作为当前项目提交项，或只存在宽泛条款、历史 fallback、父项概括证据。
```

- [ ] **Step 4: 写入状态矩阵**

在状态规则后增加：

```markdown
证据状态矩阵：

| 证据范围/强度 | 状态判断 |
| --- | --- |
| `format_area` / `parent_context` / `high_value_area` + `strong` | 可判“必要”，但仍需确认该证据指向当前节点本身。 |
| `medium` | 父级或材料级目录可判“必要”；深层子项要谨慎，多数应为“待确认”。 |
| `full_text` / `broad_clause` / `weak` | 默认“待确认”，不能把具体历史子项批量升级为“必要”。 |
| `history_fallback` / `fallback` | 默认“待确认”，禁止判“必要”。 |
| 联合体、代理商、备选方案等明确条件项 | 判“可选”。 |
```

- [ ] **Step 5: 增加父子证据规则**

加入：

```markdown
父项有强证据，不等于所有子项都“必要”。子项没有自己的当前招标文件证据时，默认“待确认”。宽泛条款只能支持 `action=keep` 或“待确认”，不能把历史具体子项批量升级成“必要”。
```

Expected:

- opencode 被明确告知：保留历史结构与判定当前必要是两条线。

---

## Task 5: 强化 4/5 级历史深层项规则

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\SKILL.md`

- [ ] **Step 1: 在“保留历史子层级”章节增加深层规则**

写入：

```markdown
对 4/5 级历史深层项必须额外谨慎：

- 没有当前招标文件逐字证据时，不得判“必要”。
- 如果是正文素材明细，例如具体证书、具体项目、具体合同、过程材料、图片/附件说明，应写入 `outline_authoring_decisions.json` 且 `action: "defer"`。
- 如果暂时无法判断是不是正文素材明细，可以 `action: "keep"` 保留目录节点，但 `required_status` 只能是“待确认”。
- 父级或材料级目录已判“必要”，不自动继承给 4/5 级子项。
```

- [ ] **Step 2: 更新质量检查清单**

在 `## 质量检查清单` 中补充：

```markdown
28. 是否没有把 `history_fallback` + `fallback` 的目录项判为“必要”。
29. 4/5 级历史深层项没有当前招标文件逐字证据时，是否为“待确认”或 `action: "defer"`。
30. 父项强证据是否没有被无条件传播给所有子项。
```

Expected:

- 深层历史明细不再因为历史结构保留而批量变成当前必要项。

---

## Task 6: 在 skill 中说明 helper 契约失败的处理方式

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\SKILL.md`

- [ ] **Step 1: 在 helper 调用说明后增加契约说明**

写入：

```markdown
`outline_authoring_helper.py` 不替 opencode 判断章节是否必要，但会拒绝明显违反证据状态契约的决策。例如所选候选为 `evidence_scope == "history_fallback"` 且 `evidence_strength == "fallback"` 时，`required_status` 不能是“必要”。遇到 helper 拒绝时，必须回到 `outline_authoring_decisions.json` 重写决策：选择当前招标文件强证据，或把状态改为“待确认”，或将正文素材明细改为 `action: "defer"`。
```

Expected:

- helper 报错后，opencode 的修复方向明确，不会继续现场写临时脚本绕过。

---

## Task 7: 全量回归测试

**Files:**
- No code changes unless tests expose regression.

- [ ] **Step 1: 运行商务目录 skill 脚本单测**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest discover -s opencode/skill/bid-business-outline-generator/scripts -p "test_*.py"
```

Expected:

- 所有测试通过。

- [ ] **Step 2: 运行后端目录生成相关测试**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_directory_generation tests.test_opencode_client
```

Expected:

- 所有测试通过。

- [ ] **Step 3: 检查 diff**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
git diff --check
```

Expected:

- 无新增 whitespace error。若只出现既有 CRLF 提示，需要在汇报中说明。

---

## Task 8: PRJ-0015 真实样本验收

**Files:**
- Read existing local PRJ-0015 manifest/workDir if available.
- Write validation artifacts only under `C:\Users\99065\Documents\商务标V2\tmp\business_outline_compare\` or existing sample workDir.

- [ ] **Step 1: 重新生成 PRJ-0015 商务目录**

优先使用现有后端/本地 manifest 跑完整链路。若本地缺少 PRJ-0015 项目状态，则使用可追溯的真实 manifest/workDir 离线跑，并在最终汇报中明确“未走前端真实项目重跑”的原因。

- [ ] **Step 2: 统计 fallback 必要项**

用本地 JSON 统计最终 `outline.json`：

```python
import json
from pathlib import Path

outline = json.loads(Path("outline.json").read_text(encoding="utf-8"))

def walk(items):
    for item in items:
        yield item
        yield from walk(item.get("children") or [])

sections = list(walk(outline["sections"]))
bad = [
    s for s in sections
    if s.get("evidence_scope") == "history_fallback"
    and s.get("evidence_strength") == "fallback"
    and s.get("required_status") == "必要"
]
print({"section_count": len(sections), "bad_history_fallback_necessary": len(bad)})
```

Expected:

- `bad_history_fallback_necessary == 0`。

- [ ] **Step 3: 确认强证据必要项没有被削弱**

统计：

```python
strong_necessary = [
    s for s in sections
    if s.get("evidence_strength") == "strong"
    and s.get("evidence_scope") in {"format_area", "parent_context", "high_value_area"}
    and s.get("required_status") == "必要"
]
print({"strong_necessary_count": len(strong_necessary)})
```

Expected:

- PRJ-0015 中已有当前招标文件强证据的 46 项仍可为“必要”。
- 如果数量不是 46，必须抽样核对差异原因，不能通过削弱召回策略或写死标题修补。

- [ ] **Step 4: 跑质量门禁作为验收证据**

Run:

```powershell
cd <PRJ-0015 workDir>
python C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\validate_outline.py outline.json
python C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\outline_quality_gate.py --outline outline.json --tender-map tender_map_inputs.json --output-report outline_quality_report.json
```

Expected:

- `validate_outline.py` 通过。
- `outline_quality_gate.py` 报告作为离线验收证据保存。
- 离线质量报告不接入线上强制门禁或自动重试机制。

---

## 验收标准

- `SKILL.md` 中不存在“历史目录项已被当前招标文件明确/宽泛要求证明应纳入”这类把保留和必要混在一起的规则。
- `SKILL.md` 明确写出状态矩阵，并说明宽泛条款、`history_fallback`、父项强证据不能批量推出子项“必要”。
- `outline_authoring_helper.py` 拒绝 `history_fallback + fallback + 必要`，但允许 `history_fallback + fallback + 待确认`。
- helper 未出现固定商务标题清单、PRJ-0015 特判、自动状态降级。
- 单测全部通过。
- PRJ-0015 重新生成后，`history_fallback + fallback` 不再出现“必要”。
- PRJ-0015 中有当前招标文件强证据的 46 项仍可为“必要”，证明 source 策略没有被削弱。

---

## 非目标

- 不修改前端。
- 不恢复 early completion。
- 不把 Python runner 改回最终目录生成器。
- 不新增固定商务标题清单。
- 不针对 PRJ-0015 写死规则。
- 不把离线质量报告变成线上强制门禁或自动重试机制。
