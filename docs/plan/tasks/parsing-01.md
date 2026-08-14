---
id: parsing-01
scope: 后端 / S1 解析链路
status: done
depends-on: []
---

# parsing-01：parsing.py（7609 行）拆分

## objective

把 `app/services/parsing.py` 按职责拆成 6 个模块，公开接口签名不变、行为不变，
`app.services.parsing.<符号>` 命名空间经门面 re-export 保持可解析、可 patch。

## context

- 拆分设计分析：2026-08-14 全量代码复核（结构盘点、依赖方向、patch 安全性分类），结论已并入本文件。
- 验证约定见根 AGENTS.md「验证建议」。

## path

- `code/sewpg-bid-backend/app/services/parsing.py`（拆分源）
- 新增：`parse_common.py`、`parse_extract.py`、`parse_business_fields.py`、`parse_appendix.py`、`parse_s1_skill.py`
- 测试仅允许改 patch target 字符串（不改断言、不改行为）：`test_parse_pipeline.py:2838`、`:2867`、`:2039`，`test_technical_parse_shards.py` 约 :660

## 现状

parsing.py 实测 7609 行，11 个区段：模块头/常量、文本提取 OCR 桥、技术标字段构建（死代码）、
商务字段/资格/承诺/评分（约 2100 行）、附表提取、docx 写入切片物化、商务模板判定、
编排胶水、S1 skill 会话链路（约 1070 行）、主编排 `parse_tender_documents`（566 行）。

## 改造方案

目标布局与依赖方向（无环）：

| 模块 | 职责 | 来源区段 | 约行数 |
|---|---|---|---|
| `parse_common.py` | 取消/心跳/协程桥/目录/文本归一 | ①③的通用件 | ~200 |
| `parse_extract.py` | docx/pdf 文本提取、OCR 兜底、docling 引擎桥 | ③ | ~400 |
| `parse_business_fields.py` | FieldSpec 族 + 商务字段/资格/承诺/评分/契约总装 | ②活部分+⑤ | ~2100 |
| `parse_appendix.py` | 附表提取、docx 切片物化、商务模板判定 | ⑥⑦⑧ | ~2700 |
| `parse_s1_skill.py` | S1 prompt/CLI/分片调度/finalize/prefill + `sys.path` 副作用 + `_S1_SHARD_REQUEST_SLOTS` | ⑩ | ~1000 |
| `parsing.py` 门面 | `parse_tender_documents` 本体 + ⑨胶水 + re-export | ⑨⑪ | ~800 |

施工步骤（每步跑测试，绿了再下一步）：

0. 删死代码约 250 行（删前逐个 grep 复核零调用）：`ParseCategory`/`PARSE_CATEGORIES`、
   日期正则常量、④区 `_build_field_groups` 整族、`_parse_business_pdf_with_document_engine`、
   `_build_business_commitment_letters/clues`、`_is/_mark_business_skill_workflow_*`、
   `parsed_appendix_dir`、`TURBINE_CORE_FIELDS`/`PERFORMANCE_FIELDS`/`ENVIRONMENT_FIELDS`。
   注意 `_strip_leading_number`/`_split_label_value`/`PROJECT_BASIC_FIELDS`/`*_CONTEXT` 是活的。
1. 搬 `parse_common` + `parse_extract`（最独立，低风险）。
2. 搬 `parse_business_fields`（几乎全纯函数；语义审查走 AgentEngineFactory 是 A 类 patch，安全）。
3. 整体搬 `parse_appendix`（簇内互调不可切半）；改 2 处测试 patch 路径到新模块。
4. 整体搬 `parse_s1_skill`（分片三件套 + sys.path 副作用单点）；改 2 处测试 patch 路径。
5. 门面收尾：`parse_tender_documents` 与 ⑨区胶水留在 parsing.py 不动；补齐 re-export。

硬约束：

- `materialize_appendix_docx` ↔ 附表提取器互调（8 处正调 + 2 处反调），切割会产生环 import。
- `DOCX_SLICE_STORED_XML_THRESHOLD_BYTES` 必须与切片函数同模块（运行时被 patch）。
- `_S1_SHARD_REQUEST_SLOTS` 只能 derive 一次（并发预算口径），facade re-export。
- `sys.path`/`PARSER_CORE_DIR` 副作用只能一个所有者，随 `parse_s1_skill` 走。
- facade 必须保留的 re-export/中转符号：`_ocr_fallback_text`、`_project_basics_project_prefill`、
  `_S1_SHARD_REQUEST_SLOTS"、`_ShardProgressAggregator`、`_technical_total_item_count`、
  `_technical_submitted_item_count`、`IMAGE_SUFFIXES`、`OpencodeEngine`、`DoclingParseEngine`、
  `AgentEngineFactory`、`AgentOrchestrator`、`system_settings_service`、`ocr_service`、`settings`、
  `subprocess`、`write_business_section_tree`、`run_business_template_extractor`。
- 收尾加一个守卫测试：`import app.services.parsing` 后断言上述符号 `hasattr` 全真。

## verification

```bash
cd code/sewpg-bid-backend
APP_STORE_BACKEND=memory \
DATABASE_URL="postgresql+asyncpg://biduser:bidpass@localhost:5432/bidplatform" \
.venv/bin/python -m pytest -m "not integration" tests/test_parse_pipeline.py \
  tests/test_technical_parse_shards.py tests/test_agent_concurrency_budget.py \
  tests/test_technical_project_prefill.py tests/test_business_section_tree.py \
  tests/test_parse_async_jobs.py tests/test_parse_event_loop_safety.py tests/test_technical_parse_assets.py
```

收尾跑全量非集成套件 + `git diff --check`。
