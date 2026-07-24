# 商务目录证据归因根因治理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `bid-business-outline-generator` 从“继承真实商务标目录但证据和状态判断薄弱”升级为“目录结构稳定、`source_text` 可追溯、`required_status` 由证据驱动、质量可验收”的商务目录生成 skill。

**Architecture:** 保留“历史/模板目录结构继承”作为目录骨架来源，不把当前问题误判为目录重排问题；新增当前招标文件的结构化证据索引、分层证据召回、证据驱动状态判定和质量门禁。所有规则必须从文档结构、章节语义、证据强度和通用商务标类别抽象得出，禁止按本次样本标题、文件名、项目名写死。

**Tech Stack:** Python 3、OOXML/zipfile、python-docx、JSON schema、unittest/pytest、现有 `bid-business-outline-generator` runner 和脚本。

---

## 1. 背景和根因判断

本计划基于当前真实商务标对比结果制定：

- 真实商务标文件：`C:\Users\99065\Documents\商务标V2\目录生成\华能赤峰市翁牛特旗等6个风电项目集采投标文件商务文件.docx`
- 对比产物目录：`C:\Users\99065\Documents\商务标V2\tmp\business_outline_compare\`
- 真实样本目录抽取：`tmp/business_outline_compare/real_history_bid_outline_inputs.json`
- 后端 runner 输出：`tmp/business_outline_compare/backend_runner/outline.json`

已确认的事实：

- 真实目录候选约 291 个；runner 输出也是约 291 个节点，层级分布基本一致，`validate_outline.py` 可通过。
- 当前主要问题不是“目录不像真实商务标”，而是 `source_text` 很多不是当前招标文件正文中的可信证据，或者只能匹配历史目录页文字。
- `check_source_text.py` 统计显示未匹配 `source_text` 集中在商务评分索引、供货保障、投标函、法定代表人身份证明、授权委托书、廉洁承诺、投标价格表、货物规格、商务偏差、投标保证金、履约保证、营业执照、财务、信用、保密承诺、合同生效、供应链协同等类别。
- `required_status` 当前大量为“待确认”，少量为“必要”，判断缺乏可解释证据链。
- `resolve_source_text_candidates.py` 在大文档上偏慢，说明当前召回方式缺少结构索引和分层检索。

根因判断：

1. 当前 `source_text` 过度依赖历史目录项或简单字符串相似度，缺少“当前招标文件正文锚点”的优先级。
2. 当前候选检索没有把 Word 文档拆成可检索结构单元，例如章节、正文块、表格行、表格单元格、格式章节范围、评分/资格/废标/递交要求等高价值区域。
3. 当前 `required_status` 与证据强度没有稳定映射，导致“必要”和“待确认”更像兜底标签，而不是可审核判断。
4. 当前质量检查只验证 schema 和字段存在，不能验收 `source_text` 是否来自原文、候选是否可信、状态是否可解释、性能是否达标。

---

## 2. 范围边界

本计划只允许修改：

- `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\`

本计划不允许修改：

- 前端页面
- 后端 service/API
- 数据库
- 存储
- 模板文件
- 其他 skill
- 真实标书文件和本地临时日志

如果执行 agent 发现 skill 输入不足、后端调用链缺字段、API 契约需要调整，只能在交付说明里记录“外部阻塞/建议”，不能顺手混改。

本计划明确不做：

- 不新增“商务必备章节固定标题清单”来硬判必要状态。
- 不按“华能赤峰市翁牛特旗等6个风电项目”这个样本的标题、文件名、项目名、章节编号写死。
- 不通过删除目录节点、降低层级、缩短 `source_text`、把 unmatched 隐藏掉来通过测试。
- 不把质量门禁设计成线上无限重试机制。质量门禁是 skill 开发验收和回归测试工具；线上失败后是否重试由调用方另行设计。

---

## 3. 目标数据契约

执行 agent 应维持现有 `outline.json` 兼容字段，同时让每个目录节点具备可审核证据。推荐字段含义如下：

- `source_text`：首选当前招标文件中的原文证据；可以是标题、正文句、表格行或表格单元格；不得首选目录页文本。
- `source_refs`：指向当前招标文件的证据引用，至少包含来源文件、块 ID 或表格定位、证据类型、所在章节路径。
- `required_status`：由证据强度和证据类别判定，允许值沿用现有契约，例如“必要”“待确认”；如现有 schema 支持更多状态，可在 Task 5 中按 schema 扩展。
- `reason`：说明该节点为什么是必要或待确认，必须引用证据类别和证据强度，不写“因为标题是某某所以必要”。
- `evidence_scope`：建议新增内部字段或调试字段，取值可包括 `parent_context`、`format_area`、`high_value_area`、`broad_clause`、`history_fallback`。
- `evidence_strength`：建议新增内部字段或调试字段，取值可包括 `strong`、`medium`、`weak`、`fallback`。

验收时允许新增调试产物，例如：

- `document_structure_index.json`
- `source_text_candidates.json`
- `outline_quality_report.json`

这些调试产物应写到 manifest 指定的 `workDir`，不能污染项目根目录。

---

## 4. 文件结构

执行 agent 应优先保持现有脚本入口兼容，逐步拆分大文件职责。

- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\prepare_tender_map_inputs.py`
  - 保持现有输出兼容。
  - 补足 blocks/tables/zones 中的结构信息，或为新索引模块提供足够原始数据。

- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\document_structure_index.py`
  - 负责从 `tender_map_inputs.json` 构建文档结构索引。
  - 输出章节、正文块、表格、表格单元格、目录页区域、格式章节区域、高价值区域和块顺序。

- Modify or split: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\resolve_source_text_candidates.py`
  - 保留 CLI 兼容。
  - 将候选召回改为使用 `document_structure_index.py`。
  - 如果文件继续膨胀，执行 agent 应拆出 `evidence_retrieval.py`。

- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\evidence_retrieval.py`
  - 负责分层证据召回和候选排序。
  - 不负责最终状态判定。

- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\status_decision.py`
  - 负责将证据类别、证据强度、目录节点层级和上下文映射为 `required_status` 与 `reason`。
  - 禁止写死样本标题清单。

- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\outline_quality_gate.py`
  - 负责离线质量门禁。
  - 输入 `outline.json`、`tender_map_inputs.json`、可选 `source_text_candidates.json`。
  - 输出质量报告和非零退出码。

- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\run_from_manifest.py`
  - 接入新证据管线。
  - 保留历史目录结构继承，禁止通过重排目录掩盖证据问题。

- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\check_source_text.py`
  - 增强匹配统计，区分“当前原文匹配”“目录页匹配”“历史 fallback”“无法匹配”。

- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\validate_outline.py`
  - 只做 schema 和字段基本校验。
  - 不把质量门禁逻辑混进 schema 校验，避免职责不清。

- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_resolve_source_text_candidates.py`
  - 增加证据召回失败用例。

- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_document_structure_index.py`
  - 覆盖结构索引。

- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_status_decision.py`
  - 覆盖状态判定。

- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_outline_quality_gate.py`
  - 覆盖质量门禁。

- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_run_from_manifest.py`
  - 覆盖 runner 端到端接入。

- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\SKILL.md`
  - 更新 skill 工作原则、输出字段说明和验收方式。

- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\references\expert-checklist.md`
  - 更新专家检查清单，强调证据追溯和状态解释，不写样本答案。

---

## 5. 任务拆解

### Task 1: 建立基线和失败测试，锁定真实问题

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_resolve_source_text_candidates.py`
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_run_from_manifest.py`
- Optional Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_outline_regression_metrics.py`

- [ ] **Step 1: 记录当前真实样本基线**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\validate_outline.py tmp\business_outline_compare\backend_runner\outline.json
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\check_source_text.py tmp\business_outline_compare\backend_runner\tender_map_inputs.json tmp\business_outline_compare\backend_runner\outline.json
```

Expected:

- `validate_outline.py` 通过。
- `check_source_text.py` 输出当前 matched/unmatched 统计。
- 执行 agent 将该统计写入任务交付说明，不写入生产代码。

- [ ] **Step 2: 增加“目录页文本不能作为首选证据”的失败测试**

测试场景要求：

- `tender_map_inputs` 同时包含目录页行和正文格式章节行。
- 目录页行标题与目录节点完全相似。
- 正文格式章节行包含更可靠的表格行或段落证据。

断言要求：

- 候选排序第一名不能是目录页文本。
- 第一名必须来自正文块、格式章节块、表格行或表格单元格。
- 候选对象必须能说明 scope，例如 `format_area` 或 `parent_context`。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest scripts.test_resolve_source_text_candidates.ResolveSourceTextCandidatesTest -v
```

Expected:

- 新增测试在当前实现下失败。
- 失败原因指向目录页候选被错误排在首位，或候选未区分目录页和正文证据。

- [ ] **Step 3: 增加“子项优先在父范围内找原文”的失败测试**

测试场景要求：

- 父节点为资格证明或商务摘要类目录。
- 子节点文本在父节点后续表格单元格中出现。
- 文档其他位置也出现相似文本，例如评分章节、资格审查章节或纯引用句。

断言要求：

- 子节点第一候选来自父节点正文范围内的表格单元格或相邻表格行。
- 不能跨到下一个兄弟节点范围。
- 不能把评分章节中的相似描述排在父范围证据之前。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest scripts.test_resolve_source_text_candidates.ResolveSourceTextCandidatesTest -v
```

Expected:

- 当前实现至少一项失败。
- 失败信息能暴露 parent scope 边界或候选排序问题。

- [ ] **Step 4: 增加“runner 不得把历史目录文本直接当当前证据”的失败测试**

测试场景要求：

- 历史目录里有完整目录结构。
- 当前招标文件中只有部分节点有正文依据。
- 无当前依据的节点允许 `history_fallback`，但必须标记 reason，且 `source_refs` 不得伪装成当前文件证据。

断言要求：

- 有当前原文的节点，`source_text` 必须来自当前招标文件。
- 没有当前原文的节点，`source_text` 可以保留历史文本，但 `reason` 必须明确“未在当前招标文件找到强证据，需要人工确认”。
- `required_status` 不得因为历史目录存在就直接判为“必要”。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest scripts.test_run_from_manifest.RunFromManifestTest -v
```

Expected:

- 当前实现失败，暴露 `run_from_manifest.py` 直接用 `first_matching_candidate` 和历史目录兜底导致的证据归因问题。

- [ ] **Step 5: 提交测试基线**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
git status --short
git add code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_resolve_source_text_candidates.py code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_run_from_manifest.py
git commit -m "test: capture business outline evidence failures"
```

Expected:

- 只提交本 task 修改的测试文件。
- 不提交真实标书和 `tmp` 目录。

---

### Task 2: 构建文档结构索引，给证据召回打地基

**Files:**
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\document_structure_index.py`
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_document_structure_index.py`
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\prepare_tender_map_inputs.py`

- [ ] **Step 1: 写结构索引失败测试**

测试输入应覆盖：

- 目录页行，例如带页码、点线、heading_path 为目录的文本。
- 正文标题行，包含章节号和 heading_path。
- 表格行和表格单元格，包含 table_id、row_index、col_index。
- 格式章节区域，例如投标文件格式、附件格式、响应文件格式。
- 高价值区域，例如评标办法、商务评分、资格审查、废标条款、投标文件递交和组成。

断言要求：

- 每个 block 都有稳定顺序 `order`。
- 能识别 `is_toc`。
- 能识别 `heading_path`。
- 能识别 `source_kind`：`paragraph`、`table_row`、`table_cell`、`zone` 等。
- 能输出 `format_ranges`，且范围从格式章节正文开始，不包含前文引用句。
- 能输出 `high_value_ranges`，且评分、资格、废标、递交要求等区域被分类。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest scripts.test_document_structure_index -v
```

Expected:

- 测试失败，原因是 `document_structure_index.py` 尚不存在或未实现。

- [ ] **Step 2: 实现最小结构索引模块**

实现要求：

- 提供一个纯函数入口，例如 `build_document_structure_index(tender_map_inputs: dict) -> dict`。
- 输入只依赖 `tender_map_inputs.json`，不重新读取 docx，避免重复解析和性能浪费。
- 输出保持 JSON 可序列化。
- 不引入新大型依赖。
- 使用通用正则和结构信号识别目录页、章节号、格式区、高价值区。
- 表格单元格应保留比整行更细的证据粒度。

禁止：

- 写死本次样本的项目名称、风电项目名称、招标编号。
- 写死完整标题清单来判断必要状态。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest scripts.test_document_structure_index -v
```

Expected:

- `test_document_structure_index.py` 通过。

- [ ] **Step 3: 检查真实样本索引体积和速度**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\document_structure_index.py tmp\business_outline_compare\backend_runner\tender_map_inputs.json --output tmp\business_outline_compare\backend_runner\document_structure_index.json
```

Expected:

- 生成 `document_structure_index.json`。
- 输出 summary 至少包含 blocks 数、tables 数、format_ranges 数、high_value_ranges 数、toc_blocks 数。
- 在普通开发机上运行时间应明显低于原 `resolve_source_text_candidates.py` 全量扫描耗时；若没有耗时统计，执行 agent 在脚本中加入 CLI summary 的 `elapsed_seconds`。

- [ ] **Step 4: 提交结构索引**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
git status --short
git add code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\document_structure_index.py code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_document_structure_index.py code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\prepare_tender_map_inputs.py
git commit -m "feat: index business tender document structure"
```

Expected:

- 只提交 skill 目录内文件。
- `tmp` 产物不提交。

---

### Task 3: 重建分层证据召回，解决 source_text 找不到原文

**Files:**
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\evidence_retrieval.py`
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\resolve_source_text_candidates.py`
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_resolve_source_text_candidates.py`

- [ ] **Step 1: 写分层召回测试**

召回层级必须按以下顺序尝试：

1. `parent_context`：父目录正文范围、父格式附件范围、父表格范围。
2. `format_area`：投标文件格式、响应文件格式、附件格式等正文区域。
3. `high_value_area`：资格、评分、废标、递交、投标文件组成、保证金、合同条款等高价值区域。
4. `broad_clause`：全局正文条款，但排除目录页和纯交叉引用。
5. `history_fallback`：当前文件没有可信证据时才回退历史目录文本。

测试断言：

- 第一候选的 `scope` 符合上述优先级。
- `source_text` 来自当前招标文件原文时，`source_refs` 必须有当前文件定位。
- 目录页和纯引用句不能压过正文锚点。
- 表格单元格证据优先于整行证据，整行证据优先于大段 zone。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest scripts.test_resolve_source_text_candidates.ResolveSourceTextCandidatesTest -v
```

Expected:

- 新增测试在当前实现下失败。

- [ ] **Step 2: 实现 evidence retrieval 纯函数**

实现要求：

- `evidence_retrieval.py` 只负责候选召回和排序，不判定 `required_status`。
- 输入：单个 outline section、父节点上下文、document structure index。
- 输出：候选列表，每个候选包含 `source_text`、`scope`、`score`、`source_kind`、`heading_path`、`source_ref`、`match_reason`。
- 候选排序必须先按 scope 层级，再按证据粒度，再按文本相似度，再按位置接近度。
- 相似度计算应基于规范化标题、去编号、关键词覆盖、短标题惩罚和泛词惩罚。
- 对“文件、资料、材料、证明、说明、响应、承诺、相关”等泛词必须降权。

禁止：

- 用一组固定商务目录标题直接映射 scope。
- 因为真实样本中某标题未匹配就新增一条专用 if 判断。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest scripts.test_resolve_source_text_candidates.ResolveSourceTextCandidatesTest -v
```

Expected:

- Task 1 和 Task 3 新增的召回测试通过。
- 既有测试仍通过。

- [ ] **Step 3: 让 resolve_source_text_candidates CLI 使用新召回**

兼容要求：

- 原 CLI 参数不变：`tender_map_inputs.json outline.json --output source_text_candidates.json`。
- 输出 JSON 顶层继续包含 `items`。
- 每个 item 的 candidates 增加或保留可审核字段，不破坏现有使用方。
- CLI summary 中输出 `candidate_count`、`unresolved_count`、`history_fallback_count`、`elapsed_seconds`。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\resolve_source_text_candidates.py tmp\business_outline_compare\backend_runner\tender_map_inputs.json tmp\business_outline_compare\backend_runner\outline.json --output tmp\business_outline_compare\backend_runner\source_text_candidates.json
```

Expected:

- 命令成功。
- `source_text_candidates.json` 存在。
- `history_fallback_count` 有统计。
- 总耗时可见。

- [ ] **Step 4: 提交证据召回**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
git status --short
git add code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\evidence_retrieval.py code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\resolve_source_text_candidates.py code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_resolve_source_text_candidates.py
git commit -m "feat: retrieve business outline evidence by document structure"
```

Expected:

- 提交只包含召回相关文件。

---

### Task 4: 建立证据驱动的 required_status，不写死必备章节

**Files:**
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\status_decision.py`
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_status_decision.py`

- [ ] **Step 1: 写状态判定失败测试**

测试应覆盖：

- 当前文件强证据，且证据来自明确要求、格式附件正文、递交组成、资格/评分/废标/保证金等高价值区域。
- 当前文件中只有弱引用句，例如“见附件”或目录页。
- 只有历史目录 fallback，没有当前文件证据。
- 子项继承父格式范围证据，但自身没有直接证据。

断言要求：

- 强证据节点可判为“必要”。
- 弱证据或仅历史 fallback 节点判为“待确认”。
- `reason` 必须说明证据 scope 和 strength。
- 测试中不得出现“标题等于某某则必要”的判断。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest scripts.test_status_decision -v
```

Expected:

- 测试失败，原因是 `status_decision.py` 尚不存在或未实现。

- [ ] **Step 2: 实现状态判定模块**

判定原则：

- `required_status` 只由证据强度、证据范围、节点层级、父子关系和通用商务标语义类别共同决定。
- “通用商务标语义类别”只能使用抽象类别，例如 `submission_requirement`、`format_appendix`、`qualification_requirement`、`scoring_response`、`bid_bond`、`contract_clause`、`material_proof`，不能使用本次样本完整标题作为规则。
- 证据来自当前招标文件正文、格式附件正文、表格单元格、资格/评分/废标/递交要求等范围时，强度高。
- 证据来自目录页、纯引用句、历史目录、过短泛词时，强度低。
- 对无法充分证明的节点保留“待确认”，但 `reason` 必须比当前更有信服力，例如说明“仅命中历史目录，未命中当前招标正文强证据”。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest scripts.test_status_decision -v
```

Expected:

- `test_status_decision.py` 通过。

- [ ] **Step 3: 建立状态分布回归指标**

在测试或质量门禁中记录：

- `necessary_count`
- `pending_count`
- `history_fallback_count`
- `weak_evidence_count`
- `strong_evidence_count`

验收原则：

- 不要求“待确认”归零。
- 不允许 291 个节点中绝大多数仍因无解释而待确认。
- 每个“待确认”必须有可审核 reason。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest scripts.test_status_decision -v
```

Expected:

- 状态判定测试通过。
- reason 覆盖弱证据和 fallback 场景。

- [ ] **Step 4: 提交状态判定**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
git status --short
git add code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\status_decision.py code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_status_decision.py
git commit -m "feat: decide business outline status from evidence"
```

Expected:

- 提交只包含状态判定模块和测试。

---

### Task 5: runner 接入证据管线，保留真实目录结构

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\run_from_manifest.py`
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_run_from_manifest.py`

- [ ] **Step 1: 写 runner 接入失败测试**

测试场景：

- manifest 提供历史模板 docx 和当前招标 docx。
- 历史模板负责生成目录骨架。
- 当前招标文件负责提供证据。

断言要求：

- 输出节点数量和层级不因证据召回失败而明显退化。
- 有当前证据的节点使用当前证据填充 `source_text`。
- 无当前证据的节点保留历史 fallback 标识和待确认 reason。
- `required_status` 来自 `status_decision.py`，不再由 `candidate exists` 直接决定。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest scripts.test_run_from_manifest.RunFromManifestTest -v
```

Expected:

- 当前实现失败，暴露 runner 尚未接入新证据管线。

- [ ] **Step 2: 接入结构索引、证据召回和状态判定**

接入顺序：

1. `prepare_history_bid_outline_inputs.py` 继续负责历史目录骨架。
2. `prepare_tender_map_inputs.py` 继续负责当前招标文档基础解析。
3. `document_structure_index.py` 基于 tender map 构建结构索引。
4. `evidence_retrieval.py` 为每个目录节点生成候选。
5. `status_decision.py` 为每个节点写入 `required_status` 和 `reason`。
6. `run_from_manifest.py` 写出 `outline.json`，同时可写出调试产物。

实现约束：

- 保持 CLI 和 summary 契约兼容。
- 不删除历史目录中的节点来提升证据匹配率。
- `outline_source` 可以说明目录骨架来自历史模板，但节点 `source_text` 应尽量来自当前招标文件。
- 对 history fallback 节点必须可见可审，不要隐藏。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest scripts.test_run_from_manifest.RunFromManifestTest -v
```

Expected:

- runner 测试通过。

- [ ] **Step 3: 用真实样本复跑 runner**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\run_from_manifest.py tmp\business_outline_compare\manifest.json --response summary
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\validate_outline.py tmp\business_outline_compare\backend_runner\outline.json
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\check_source_text.py tmp\business_outline_compare\backend_runner\tender_map_inputs.json tmp\business_outline_compare\backend_runner\outline.json
```

Expected:

- `validate_outline.py` 通过。
- 节点数量和层级与历史目录基线保持接近，不出现大面积丢节点。
- `check_source_text.py` 的 unmatched 数明显低于当前基线。
- `required_status` 的 reason 具备证据解释。

- [ ] **Step 4: 提交 runner 接入**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
git status --short
git add code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\run_from_manifest.py code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_run_from_manifest.py
git commit -m "feat: wire evidence pipeline into business outline runner"
```

Expected:

- 提交只包含 runner 和测试相关文件。

---

### Task 6: 建立目录质量门禁，用于 skill 验收和回归

**Files:**
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\outline_quality_gate.py`
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_outline_quality_gate.py`
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\check_source_text.py`

- [ ] **Step 1: 写质量门禁失败测试**

门禁应检查：

- schema 合法。
- 节点数量没有相对基线明显退化。
- 核心目录类别有当前原文证据或明确 fallback reason。
- `source_text` 当前原文匹配率达到阈值。
- 目录页命中不能被统计为强证据。
- `history_fallback` 节点必须有 reason。
- `required_status` 分布不能全靠“待确认”兜底。
- 性能不超过指定上限。

建议阈值：

- 真实样本节点数量不得低于历史基线的 95%。
- 当前原文强/中证据覆盖率先设为不低于 80%，后续可随样本集提升。
- `history_fallback` 必须 100% 有 reason。
- 质量门禁脚本对真实样本的执行时间应在可接受范围内；执行 agent 根据本机初测给出实际上限，但不得无限制。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest scripts.test_outline_quality_gate -v
```

Expected:

- 测试失败，原因是 `outline_quality_gate.py` 尚不存在或门禁未实现。

- [ ] **Step 2: 实现质量门禁 CLI**

CLI 要求：

- 输入参数包含 `--outline`、`--tender-map`、`--output-report`。
- 可选参数包含 `--baseline-outline`、`--min-current-evidence-ratio`、`--max-history-fallback-ratio`、`--max-elapsed-seconds`。
- 输出 JSON report，包含 passed、metrics、issues。
- 不通过时返回非零退出码。

用途说明：

- 这是 skill 开发验收和回归测试工具。
- 它不负责线上自动重试，也不负责调用大模型重新生成。
- 如果门禁失败，执行 agent 应修复证据索引、召回或状态判定，再重新运行 runner。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest scripts.test_outline_quality_gate -v
```

Expected:

- 质量门禁单测通过。

- [ ] **Step 3: 在真实样本上运行质量门禁**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\outline_quality_gate.py --outline tmp\business_outline_compare\backend_runner\outline.json --tender-map tmp\business_outline_compare\backend_runner\tender_map_inputs.json --baseline-outline tmp\business_outline_compare\backend_runner\outline.json --output-report tmp\business_outline_compare\backend_runner\outline_quality_report.json
```

Expected:

- 生成 `outline_quality_report.json`。
- 如果首次不通过，报告必须指出具体失败项，例如 unmatched 过高、fallback 无 reason、目录页证据误判、性能超限。
- 执行 agent 不应修改阈值来掩盖失败，应回到 Task 2-5 修复根因。

- [ ] **Step 4: 提交质量门禁**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
git status --short
git add code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\outline_quality_gate.py code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_outline_quality_gate.py code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\check_source_text.py
git commit -m "test: add quality gate for business outline evidence"
```

Expected:

- 提交只包含质量门禁和检查脚本。

---

### Task 7: 性能治理，避免大文档召回变慢

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\document_structure_index.py`
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\evidence_retrieval.py`
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_resolve_source_text_candidates.py`
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_outline_quality_gate.py`

- [ ] **Step 1: 增加性能回归测试**

测试应构造较大的 synthetic tender map：

- 至少数千个 blocks。
- 多个 tables 和 table cells。
- 多个格式区和高价值区。
- 数百个 outline sections。

断言要求：

- 结构索引构建只做一次。
- 单个 section 候选召回不能每次全量扫描所有 blocks。
- 总耗时低于测试设定上限。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest scripts.test_resolve_source_text_candidates.ResolveSourceTextCandidatesTest -v
python -m unittest scripts.test_outline_quality_gate -v
```

Expected:

- 当前实现可能失败或耗时过高。

- [ ] **Step 2: 优化索引和召回策略**

优化方向：

- 在 `document_structure_index.py` 中预计算 normalized_text、title_key、key_terms。
- 建立按首字/关键词/章节类别/区域类别的轻量倒排索引。
- 为每个父节点缓存 parent range，子节点直接在该范围内搜索。
- 候选数设置合理上限，例如每层 scope 保留前 N 个，不把所有弱候选写入输出。
- 对长 zone 只用于上下文，不直接作为首选 `source_text`。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
Measure-Command { python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\resolve_source_text_candidates.py tmp\business_outline_compare\backend_runner\tender_map_inputs.json tmp\business_outline_compare\backend_runner\outline.json --output tmp\business_outline_compare\backend_runner\source_text_candidates.json }
```

Expected:

- 执行时间较优化前下降。
- 输出候选质量不下降，Task 6 门禁仍通过。

- [ ] **Step 3: 提交性能优化**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
git status --short
git add code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\document_structure_index.py code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\evidence_retrieval.py code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_resolve_source_text_candidates.py code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\test_outline_quality_gate.py
git commit -m "perf: index evidence retrieval for large business tenders"
```

Expected:

- 提交只包含性能相关改动。

---

### Task 8: 更新 skill 文档和专家检查清单

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\SKILL.md`
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\references\expert-checklist.md`

- [ ] **Step 1: 更新 SKILL.md**

文档必须说明：

- 目录骨架来自历史/模板商务标，不代表节点证据也来自历史。
- `source_text` 应优先来自当前招标文件正文、表格或格式附件。
- 目录页文本、纯引用句、历史目录文本只能作为弱证据或 fallback。
- `required_status` 由证据强度和证据类别判断，不使用固定标题清单。
- 质量门禁用于开发验收，不是线上无限重试策略。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
rg -n "source_text|required_status|质量门禁|固定标题|历史目录" code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\SKILL.md
```

Expected:

- 能搜索到新原则。
- 文档没有把本次真实样本标题写成答案。

- [ ] **Step 2: 更新 expert-checklist.md**

清单必须增加：

- source_text 是否能在当前招标文件正文找到。
- 是否误用目录页文本作为强证据。
- 子项证据是否来自父范围或相关格式附件。
- 状态 reason 是否解释了证据强弱。
- fallback 是否明确提示人工确认。

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
rg -n "当前招标文件|目录页|父范围|fallback|人工确认|证据" code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\references\expert-checklist.md
```

Expected:

- 能搜索到新增检查项。
- 不出现样本专用答案。

- [ ] **Step 3: 提交文档更新**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
git status --short
git add code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\SKILL.md code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\references\expert-checklist.md
git commit -m "docs: document business outline evidence rules"
```

Expected:

- 只提交 skill 文档和专家清单。

---

### Task 9: 真实样本总验收

**Files:**
- No production file changes expected.
- Generated local artifacts only under `C:\Users\99065\Documents\商务标V2\tmp\business_outline_compare\backend_runner\`

- [ ] **Step 1: 清理旧 runner 产物但保留 manifest**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
Remove-Item -LiteralPath tmp\business_outline_compare\backend_runner\outline.json -ErrorAction SilentlyContinue
Remove-Item -LiteralPath tmp\business_outline_compare\backend_runner\source_text_candidates.json -ErrorAction SilentlyContinue
Remove-Item -LiteralPath tmp\business_outline_compare\backend_runner\outline_quality_report.json -ErrorAction SilentlyContinue
```

Expected:

- 只删除本地临时产物。
- 不删除真实标书。

- [ ] **Step 2: 复跑完整 runner**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\run_from_manifest.py tmp\business_outline_compare\manifest.json --response summary
```

Expected:

- 命令成功。
- 生成新的 `outline.json`、`tender_map_inputs.json`、`history_bid_outline_inputs.json`。
- summary 中能看到证据或质量相关统计。

- [ ] **Step 3: schema、证据、质量三重验收**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\validate_outline.py tmp\business_outline_compare\backend_runner\outline.json
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\check_source_text.py tmp\business_outline_compare\backend_runner\tender_map_inputs.json tmp\business_outline_compare\backend_runner\outline.json
python code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\scripts\outline_quality_gate.py --outline tmp\business_outline_compare\backend_runner\outline.json --tender-map tmp\business_outline_compare\backend_runner\tender_map_inputs.json --output-report tmp\business_outline_compare\backend_runner\outline_quality_report.json
```

Expected:

- schema 校验通过。
- `source_text` 当前原文匹配率明显优于原 223/293 matched、70 unmatched 的基线。
- `required_status` 仍允许有“待确认”，但每个待确认都有可信 reason。
- 质量门禁通过；若不通过，执行 agent 应根据 report 回到具体 task 修复，而不是降低阈值或硬写规则。

- [ ] **Step 4: 运行 skill 全量测试**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator
python -m unittest discover -s scripts -p "test_*.py" -v
```

Expected:

- skill 目录下测试全部通过。

- [ ] **Step 5: 检查无越界改动**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2
git status --short
```

Expected:

- 改动只在 `code\sewpg-bid-backend\opencode\skill\bid-business-outline-generator\` 和本计划文件。
- 不包含真实标书、`tmp` 产物、前端、后端 service/API、其他 skill。

---

## 6. 验收标准

最终执行 agent 交付时必须报告以下指标：

- `outline_section_count`：生成目录节点数。
- `level_distribution`：各层级节点数。
- `source_text_total`、`source_text_matched_current`、`source_text_matched_toc_only`、`source_text_history_fallback`、`source_text_unmatched`。
- `required_status_distribution`：必要、待确认等状态数量。
- `history_fallback_without_reason`：必须为 0。
- `quality_gate_passed`：必须为 true。
- `resolve_elapsed_seconds` 和 `runner_elapsed_seconds`。

质量目标：

- 目录结构不得相对当前 291 节点基线明显退化。
- `source_text` unmatched 数必须明显下降。
- 目录页文本不得作为强证据。
- 大量“待确认但没有解释”的情况必须消失。
- 性能不能因为全量扫描而在真实大文档上不可接受。

---

## 7. 风险和处理

- 如果当前招标文件确实没有某个历史目录节点对应证据：保留节点，但标为 `history_fallback` 和“待确认”，不要伪造当前证据。
- 如果后端 manifest 没有传入足够文件：在交付说明记录外部调用链问题，不修改 service/API。
- 如果质量门禁首次不通过：读取 `outline_quality_report.json`，定位到索引、召回或状态判定的具体原因，再回到对应 task 修复。
- 如果某些真实商务目录项只能从投标文件格式附件中间接证明：允许作为中等或强证据，但 reason 必须说明证据来自格式附件要求。

---

## 8. 自查结果

- Spec coverage：已覆盖用户提出的重点，包括 `source_text` 原文匹配、商务目录必备章节状态规则但不写死、暂不处理第三点、解释第四点“目录结构基本一致所以不作为主问题”、质量门禁用途、性能和质量提升、根因治理而非补丁。
- Placeholder scan：本文不包含待填占位项；所有任务均给出文件、命令、预期结果和验收口径。
- Type consistency：计划中的模块边界保持一致，`document_structure_index.py` 负责索引，`evidence_retrieval.py` 负责召回，`status_decision.py` 负责状态，`outline_quality_gate.py` 负责验收。
- Scope check：所有实现任务限制在 `bid-business-outline-generator` skill 目录内，未安排前端、API、service、数据库或其他 skill 改动。
