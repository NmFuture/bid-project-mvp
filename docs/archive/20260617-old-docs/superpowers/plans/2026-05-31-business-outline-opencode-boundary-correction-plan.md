# 商务目录 Opencode Skill 边界纠偏 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 恢复 `bid-business-outline-generator` 的正确职责边界：Python 脚本只准备结构化输入、证据候选和质量检查，最终商务目录 `outline.json` 必须由 opencode skill 根据 `SKILL.md` 判断并写入。

**Architecture:** 后端仍通过 opencode 启动 `business-outline <manifest>`，但该命令不得生成最终 `outline.json`。本地脚本负责产出 `history_bid_outline_inputs.json`、`tender_map_inputs.json`、`document_structure_index.json`、`source_text_candidates.json` 等候选材料；opencode 消费这些材料后完成目录结构判断、`source_text` 选择、`required_status` 判定和最终 `outline.json` 写入；质量门禁只在最终产物之后验收。

**Tech Stack:** Python 3、opencode skill、FastAPI 后端现有目录生成链路、unittest/pytest、JSON 文件产物。

---

## 背景判断

当前实现存在职责漂移：

- `run_from_manifest.py` 已经直接生成目录骨架、匹配证据、调用 `status_decision.py` 判定状态，并写入最终 `outline.json`。
- 后端 `opencode_client.py` 的 early completion 看到 `business-outline` 命令完成且 `outline.json` 存在后，会直接读取脚本产物，不再等待 opencode 继续执行 `SKILL.md` 的最终判断步骤。
- 这会让目录生成变成本地 Python 规则/算法驱动，而不是 opencode skill 负责最终语义判断。

本计划要纠偏的不是证据索引和召回能力本身；这些能力应该保留，但只能作为 opencode 的输入和验收依据。

---

## 范围边界

允许修改：

- `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\`
- 必要时修改后端目录生成集成：
  - `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\app\services\outline_generation.py`
  - `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\app\services\opencode_client.py`

不允许修改：

- 前端页面，除非用户后续明确要求展示新状态。
- 其他 skill。
- 真实标书文件、模板文件和 `tmp` 产物。

---

## 目标边界

执行完成后必须满足：

- `business-outline <manifest>` 命令只生成输入和候选材料，不生成最终 `outline.json`。
- `run_from_manifest.py` 不再调用最终目录状态判定逻辑来写 `sections[]`。
- `source_text_candidates.json` 可以包含候选、scope、score、strength、reason，但不得被视为最终目录。
- `status_decision.py` 如果保留，只能提供 `status_suggestions.json` 或候选建议，不能直接写入最终 `required_status`。
- opencode 必须继续执行 `SKILL.md` 中“学习历史目录、分析当前招标文件、选择 source_text、判断 required_status、写入 outline.json”的步骤。
- 后端 early completion 不能因为准备阶段产物完成而提前结束最终 opencode 判断。

---

## 文件职责调整

- Modify: `...\bid-business-outline-generator\scripts\run_from_manifest.py`
  - 改回“准备脚本”职责。
  - 输出输入材料和候选材料。
  - 不写最终 `outline.json`。

- Modify: `...\bid-business-outline-generator\scripts\resolve_source_text_candidates.py`
  - 保留当前结构索引和分层召回能力。
  - 输出候选，供 opencode 消费。

- Modify: `...\bid-business-outline-generator\scripts\status_decision.py`
  - 改名或降级为建议模块更合适，例如 `status_suggestions.py`。
  - 如果保留原文件名，也必须明确它只输出建议，不代表最终判定。

- Modify: `...\bid-business-outline-generator\SKILL.md`
  - 强化“脚本只准备候选，不写最终 outline”的执行说明。
  - 明确 opencode 生成最终 `outline.json` 前必须消费候选文件。

- Modify: `...\app\services\outline_generation.py`
  - 更新 prompt，使 opencode 在准备命令结束后继续判断。
  - 明确最终 `outline.json` 只能由 opencode 后续判断写入。

- Modify if needed: `...\app\services\opencode_client.py`
  - 避免 `business-outline` 准备命令完成后 early completion。
  - 对商务目录生成可以禁用 early completion，或只在检测到“最终 outline 已由 opencode 明确写入”时结束。

- Modify tests under `...\bid-business-outline-generator\scripts\test_*.py`
  - 增加边界测试，防止脚本再次越权生成最终目录。

---

## Task 1: 写边界回归测试，先锁定当前错误

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_run_from_manifest.py`
- Modify if needed: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\app\services\tests` 或现有后端测试目录

- [ ] 增加测试：执行 `run_from_manifest.py --response summary` 后，不应生成最终 `outline.json`。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest scripts.test_run_from_manifest -v
```

Expected:

- 当前实现应失败，因为它会写最终 `outline.json`。

- [ ] 增加测试：准备脚本应生成候选材料。

Expected files:

- `history_bid_outline_inputs.json`
- `tender_map_inputs.json`
- `document_structure_index.json`
- `source_text_candidates.json`

Expected:

- 这些文件存在并包含可供 opencode 使用的 summary。
- `summary` 返回这些文件路径。

- [ ] 增加测试：候选产物不得被后端视为最终目录。

Expected:

- 准备阶段产物 schema 不应伪装成 `business_bid_outline.v1` 最终产物。
- 如果有 `status_suggestions`，字段名必须体现 suggestion，而不是 final decision。

---

## Task 2: 将 runner 改回准备脚本

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\run_from_manifest.py`

- [ ] 移除最终 `outline.json` 写入职责。

要求：

- 保留历史目录输入抽取。
- 保留招标文件结构解析。
- 保留文档结构索引生成。
- 保留 `source_text_candidates.json` 生成。
- 不生成 `sections[]` 最终目录树。
- 不调用最终 `decide_required_status` 写入目录节点。

- [ ] 调整 stdout summary。

summary 应返回：

- `schema_version`
- `skill`
- `historyBidOutlineInputsFile`
- `tenderMapInputsFile`
- `documentStructureIndexFile`
- `sourceTextCandidatesFile`
- `summary`

summary 不应返回：

- `businessOutlineFile`，除非明确标为 expected output path 且文件不存在。
- 最终 `sections[]`。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\run_from_manifest.py tmp\business_outline_compare\manifest.json --response summary
```

Expected:

- 命令成功。
- 候选材料生成。
- `outline.json` 不存在，或若历史遗留存在必须先清理后验证不会重新生成。

---

## Task 3: 降级状态判定模块为建议，不替代 opencode

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\status_decision.py`
- Modify/Create tests as needed.

- [ ] 明确模块职责：只产出建议，不产出最终 `required_status`。

可选方案：

- Rename to `status_suggestions.py`，执行 agent 同步测试引用。
- 或保留文件名，但输出字段必须是 `suggested_required_status`、`suggested_reason`。

- [ ] 更新测试断言。

Expected:

- 单测仍覆盖证据强弱到状态建议的映射。
- 测试名称和断言不再表达“最终判定”。

---

## Task 4: 修正后端 opencode 调用和 early completion

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\app\services\outline_generation.py`
- Modify if needed: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\app\services\opencode_client.py`

- [ ] 修改商务目录 prompt。

要求：

- 保留先调用 `business-outline <manifest>` 准备材料。
- 明确准备命令完成后，opencode 必须继续读取候选材料并写最终 `outline.json`。
- 明确准备命令 stdout 不是最终结果。

- [ ] 禁止商务目录在准备命令完成后 early completion。

推荐方案：

- 对 `BUSINESS_OUTLINE_SKILL_COMMAND` 不传 `early_tool_command`。
- 或给 `generate_outline_with_trace` 增加参数，使商务目录要求最终 JSON 响应来自 assistant，而不是从 bash 产物合成。

验收：

- 如果 `run_from_manifest.py` 只生成候选材料，后端不能立即完成。
- 缺少最终 `outline.json` 时，应继续等待 opencode 后续判断；若最终仍缺失，应报错，而不是读取候选材料假装成功。

---

## Task 5: 更新 SKILL.md 和专家清单

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\SKILL.md`
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\references\expert-checklist.md`

- [ ] 强化边界说明。

必须写清：

- 准备脚本只生成候选材料。
- `source_text_candidates.json` 是证据候选，不是最终目录。
- `status_suggestions` 是建议，不是最终状态。
- 最终 `outline.json` 只能由 opencode 根据 `SKILL.md` 判断后写入。

- [ ] 删除或改写与当前边界冲突的描述。

重点检查：

- “runner 接入证据管线并写 outline”这类表述。
- “脚本直接生成最终目录”的暗示。

---

## Task 6: 端到端验收

**Files:**
- No production file changes expected in this task.

- [ ] 清理真实样本工作目录中的旧 `outline.json`。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
Remove-Item -LiteralPath tmp\business_outline_compare\backend_runner\outline.json -ErrorAction SilentlyContinue
```

- [ ] 单独运行准备脚本。

Run:

```powershell
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\run_from_manifest.py tmp\business_outline_compare\manifest.json --response summary
```

Expected:

- 生成候选材料。
- 不生成最终 `outline.json`。

- [ ] 通过后端/opencode 触发完整目录生成。

Expected:

- opencode 会在准备命令后继续执行最终判断。
- 最终 `outline.json` 由 opencode 写入。
- 前端不应在准备阶段完成后立即跳转。

- [ ] 对最终 `outline.json` 执行质量验收。

Run:

```powershell
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\validate_outline.py tmp\business_outline_compare\backend_runner\outline.json
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\check_source_text.py tmp\business_outline_compare\backend_runner\tender_map_inputs.json tmp\business_outline_compare\backend_runner\outline.json
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\outline_quality_gate.py --outline tmp\business_outline_compare\backend_runner\outline.json --tender-map tmp\business_outline_compare\backend_runner\tender_map_inputs.json --output-report tmp\business_outline_compare\backend_runner\outline_quality_report.json
```

Expected:

- schema 通过。
- `source_text` 匹配率优于修改前基线。
- `required_status` 有证据解释。
- 质量门禁通过或给出明确问题报告。

---

## 最终验收标准

- 准备脚本不再生成最终 `outline.json`。
- 后端不会因为准备脚本完成而把商务目录任务标记为完成。
- 最终 `outline.json` 由 opencode skill 判断后写入。
- 证据索引、分层召回、质量门禁能力保留。
- 没有新增固定标题清单或样本专用规则。
- 前端点击目录生成的耗时应反映 opencode 完整执行，而不是只反映 Python 准备脚本耗时。

---

## 给执行 agent 的注意事项

- 不要简单回滚全部证据管线改动；要保留“找原文”的能力，只把最终判断权还给 opencode。
- 不要把质量门禁前置成生成逻辑；质量门禁只验收最终产物。
- 不要为了让任务变快而恢复 early completion。
- 不要修改前端绕过问题。
- 每个提交都说明它是在恢复哪个边界。
