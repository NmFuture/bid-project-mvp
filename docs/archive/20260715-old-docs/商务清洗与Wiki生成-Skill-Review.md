# 商务素材清洗 & 商务 Wiki 生成 Skill —— 整体 Review

> 评审日期：2026-05-31
> 评审范围：
> - `code/sewpg-bid-backend/opencode/skills/bid-business-wiki-material-builder`（商务 Wiki 生成）
> - `code/sewpg-bid-backend/opencode/skills/bid-material-format-cleaner`（商务素材清洗）
> 参照：`doc/需求梳理.md`，并结合后端生产集成代码（`app/services/*`）。

---

## 0. 总体结论

两个 skill 的**核心算法都能跑，且已经接进生产链路**：1

- 清洗：`app/services/material_cleaning.py` → 调用 cleaner 的 `driver.py`
- Wiki：`app/services/wiki_generation.py:1629` → `business_wiki_blueprint.build_business_wiki_blueprint()`

真正的问题**不在"跑不跑得起来"**，而在两点：

1. **SKILL.md 文档与实际生产代码已经脱节**（尤其 Wiki 侧，文档描述的是"AI 生成"路线，生产跑的是"确定性 Python 脚本"）。
2. **若干生产稳健性隐患**（缺 import、依赖环境、取产物方式脆弱等）。

---

## 1. 关键架构事实（先对齐认知）

### 1.1 Wiki 生成的真实路径是"确定性脚本"，不是 LLM

生产调用链：

```
wiki_generation._run_local_wiki_skill(manifest, bid_type)
  -> run_from_manifest.py
    -> build_business_wiki_blueprint(inventory)   # 纯 Python，1655 行决定全部输出
```

- `generator = "local_skill"`，`providerId = "local-skill"`，`modelId = skill_name`
- **LLM 完全不参与** Wiki 节点的生成

对"商务标绝不能编造金额/承诺/证书编号"的场景，**确定性脚本其实是正确选择**。问题是文档没有反映这一点。

### 1.2 清洗的真实路径

`material_cleaning.clean_material_file()`：

1. 从 MinIO 下载原文件到临时 `source/`
2. `subprocess` 调 `driver.py`，设 `FORMAT_CLEANER_ALLOW_SYSTEM_PY=1`、`--no-feishu`
3. 读 `cleaning_manifest.json` + 解析控制台行，回写素材 `ext_fields`（`cleanResultStatus`、`cleanRelativeOutputPath` 等）
4. 把清洗后的 docx 上传回 MinIO

---

## 2. `bid-business-wiki-material-builder`（Wiki 生成）

### 🔴 P0-A：SKILL.md 描述"AI 生成"，生产跑"确定性脚本"

**现象**：SKILL.md 通篇是给 LLM 看的 prompt 契约（"仅输出 JSON、不要 Markdown 包裹、从 `materialInventory.items` 生成…"），但生产根本不调 LLM。

**后果**：
- 后端 `_build_wiki_generation_prompt` / `generate_wiki_blueprint_with_trace` / `_build_wiki_tool_prompt` 在 `app/` 内**已无任何调用方**（grep 验证为死代码）。
- SKILL.md 对真正干活的 `business_wiki_blueprint.py` **零描述**。改 wiki 行为的人会被文档带偏到 LLM 路线。

**建议**：
- 明确二选一。既然生产已定走脚本，则把 SKILL.md 重写为"脚本工具说明"（参照 cleaner 的 SKILL.md：配置 → 入口 → 输出契约 → 字段表 → 注意事项）。
- 删除后端死掉的 LLM prompt 路线（`_build_wiki_generation_prompt` 等）。

### 🔴 P0-B：SKILL.md 模块清单与脚本产出对不上

| 维度 | SKILL.md（L107–120） | 脚本 `MODULE_CONFIGS` |
|---|---|---|
| 模块数 | 11 个 | **13 个** |
| 多出来的 | — | `01-商务评分索引表`、`13-供应链协同模块` |
| 命名风格 | "投标函与授权" | "02-投标函与授权模块"（带编号 + "模块"后缀） |

脚本实际 13 模块：

```
BM-01 01-商务评分索引表
BM-02 02-投标函与授权模块
BM-03 03-投标价格表模块
BM-04 04-货物规格一览表模块
BM-05 05-商务偏差表模块
BM-06 06-投标保证金模块
BM-07 07-履约保证承诺模块
BM-08 08-资格证明文件模块（附件7）
BM-09 09-业绩情况表模块（附件7I）
BM-10 10-开标价格表模块
BM-11 11-其他说明与承诺模块（附件9）
BM-12 12-否决项与符合性响应模块
BM-13 13-供应链协同模块
```

**后果**：按 SKILL.md 找模块会找不到 `01-商务评分索引表`、`13-供应链协同模块`。文档已成误导源。

**建议**：SKILL.md 的模块清单严格与 `MODULE_CONFIGS` 同步（最好直接表格化 module_code / module_name / usage_mode / 路径前缀）。

### 🟡 P1-A：OCR / 时效 / 编号靠正则启发式（兜底做得对，但要写清）

- `infer_validity_status`、`extract_document_number`、`extract_issuer`、`DATE_RE/DOC_NO_RE/ISSUER_RE` 全是正则猜测，中文证书版式差异大、命中率有限。
- **好的一面**：脚本在 `needs_human_confirm`、`validity_status=pending_verify`、`risk_notes` 上做了保守兜底，符合需求"商务标证据经常败在有效期"的判断。
- 这不是 bug，但要在 SKILL.md 显式标注：这些字段是"提示性"的，真值依赖人工审核环节（需求第 4 节"素材和填写审核"）。

### 🟡 P1-B：`card_id` 唯一性依赖 `item.id`，输入契约未写明

- `profile_material`：`card_id = f"biz-card-{item.get('id') or Path(path).stem}"`
- 若某些 inventory item 没 `id`，退化用文件名 stem，**不同目录同名文件会撞 card_id**，导致映射表 `candidate_card_ids` 指向歧义。
- 来源是 RawFile，应有 id，但 SKILL.md 没把"item.id 必填"写进输入契约。

**建议**：在 SKILL.md 的输入契约里明确 `materialInventory.items[].id` 必填且全局唯一；后端构建 inventory 时确认每条都注入。

### 🟢 P2：可读性

- `build_evidence_segments` 上限 18、各处关键词 limit 等魔法数字散落。不影响功能，可后续抽常量。

---

## 3. `bid-material-format-cleaner`（素材清洗）

### 🔴 P0-C：`driver.py` 使用 `Any` 但未 import

- `driver.py:770`、`driver.py:787` 注解返回类型 `dict[str, Any]`，文件顶部**没有** `from typing import Any`。
- 目前靠 `from __future__ import annotations`（注解变字符串、延迟求值）侥幸不崩，但：
  - mypy / pyright 会直接报 `undefined name "Any"`
  - 是确凿代码缺陷，只是被延迟求值掩盖
- 对照：`business_wiki_blueprint.py` 已正确 `import Any`，只有 cleaner 的 driver 漏了。

**修复**：import 区补 `from typing import Any`（一行）。

### 🟡 P1-C：`.doc` 依赖 LibreOffice，镜像不一定装

- `_process_doc_word` → `_find_soffice()`，找不到即 `FAIL`。
- 需求第 6 节商务标素材库要收"资质/证书/授权/承诺函"——历史文件**大量是 `.doc`**。
- `material_cleaning.py` 设了 `FORMAT_CLEANER_ALLOW_SYSTEM_PY=1`，但**没保证镜像有 soffice**。

**建议**：确认生产镜像安装 libreoffice；否则一批 `.doc` 直接 FAIL，而 SKILL.md 把这描述成"确定性 FAIL"听起来像设计，实际是环境缺失。

### 🟡 P1-D：图片证据范围未对齐 & SKILL.md 未提

- cleaner `SUPPORTED_SUFFIXES = {.pdf, .xlsx, .xls, .xlsm, .docx, .doc}`，**不含图片**——这是对的（符合"图片直挂原件"）。
- 但 wiki 脚本大量逻辑（`IMAGE_EXTS`、`extract_image`、`scan_image`、"图片不触发清洗"）假设图片素材存在。
- cleaner 的 SKILL.md 对图片**只字未提**，会让人误以为图片也会被处理。

**建议**：cleaner SKILL.md 补一句"图片类不在清洗范围，由 wiki 侧按原件挂载"，与 wiki 侧对齐边界。

### 🟡 P1-E：取清洗产物用"最新 mtime"，而非 manifest 精确匹配

- `clean_material_file:225`：`candidates = sorted(output_dir.rglob("*.docx"), key=mtime, reverse=True)`，取 `candidates[0]`。
- 单文件场景问题不大；但写法脆——若 PDF 分支顺带产出旁路 docx，或将来批量化，会拿错文件。
- manifest 里已有 `relativeOutputPath`，却没用上。

**建议**：直接用 `manifest_record["relativeOutputPath"]` 定位产物。

### 🟢 P2：飞书 webhook 硬编码

- `driver.py:38` 硬编码 `WEBHOOK = "https://open.feishu.cn/...a343d185..."`。
- 后端调用已 `--no-feishu` 规避，但 token 进版本库不利于轮换/防泄露。

**建议**：挪到环境变量。

---

## 4. 跨 Skill / 对照需求的缺口（超出本次两个 skill，但需确认）

### 4.1 `bid-business-fact-table-builder` skill 不存在

- 需求第 112 行明确要新增此 skill。
- 现状：事实表由后端 `app/services/business_gap_fact_table.py` 实现（`PROJECT_FACT_TABLE_SCHEMA_VERSION = "bid-project-fact-table-v1"`），**不是 skill 形态**。
- 它是 wiki/清洗的下游消费者，需确认是"故意改后端脚本"还是"漏做 skill"。

### 4.2 共用业绩库是否打通到 Wiki

- 需求第 7 节：业绩库 = PostgreSQL 业绩字段 + 对象桶 Word 文件。
- wiki 脚本只从 `materialInventory.items` 取数，**没有**从业绩库专门取业绩字段。
- 若业绩库是独立数据源，wiki 生成时可能看不到业绩 → 需确认 inventory 是否已把业绩库 merge 进去（对应 `03-业绩资产池` / `BM-09 业绩情况表`）。

---

## 5. 优先修复清单（按性价比）

| 优先级 | 项 | 动作 | 风险 |
|---|---|---|---|
| P0 | cleaner `driver.py` 缺 `from typing import Any` | 补一行 import | 极低 |
| P0 | wiki SKILL.md 与脚本脱节（路线 + 模块清单） | 重写 SKILL.md 为脚本工具说明；同步 13 模块 | 低（仅文档） |
| P0 | 后端 wiki LLM prompt 死代码 | 删 `_build_wiki_generation_prompt` 等 | 低（确认无调用方后删） |
| P1 | `.doc` 依赖 soffice / 图片范围 | 确认镜像装 libreoffice；SKILL.md 补图片说明 | 中（环境） |
| P1 | `material_cleaning` 取产物用 mtime | 改用 manifest 的 `relativeOutputPath` | 低 |
| P1 | wiki `card_id` 唯一性 | inventory 输入契约写明 id 必填 | 低 |
| P2 | 飞书 webhook 硬编码 | 挪到环境变量 | 低 |

---

## 6. 涉及文件索引（便于定位修改）

**Skill 侧**
- `opencode/skills/bid-business-wiki-material-builder/SKILL.md`
- `opencode/skills/bid-business-wiki-material-builder/scripts/business_wiki_blueprint.py`（核心，1655 行）
- `opencode/skills/bid-business-wiki-material-builder/scripts/run_from_manifest.py`
- `opencode/skills/bid-material-format-cleaner/SKILL.md`
- `opencode/skills/bid-material-format-cleaner/scripts/driver.py`（总控）
- `opencode/skills/bid-material-format-cleaner/scripts/{pdf_to_word,excel_to_word,word_cleaner}.py`

**后端集成侧**
- `app/services/wiki_generation.py`（Wiki 编排；含死代码 prompt 路线）
- `app/services/business_wiki_blueprint.py`（仅是 skill 脚本的 re-export shim）
- `app/services/material_cleaning.py`（清洗编排）
- `app/services/opencode_client.py`（含已无调用方的 `generate_wiki_blueprint_with_trace`）
- `app/services/business_gap_fact_table.py`（事实表，非 skill 形态）
