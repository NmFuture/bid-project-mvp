---
id: engine-01
scope: AgentEngine / 协议边界与改名
status: in-progress
depends-on: []
---

# engine-01（波次 A0）：AgentEngine 协议 + 工厂 + OpencodeClient → OpencodeEngine 纯改名

## objective

立起 `AgentEngine` 边界：定义引擎协议、公共类型与 `AgentEngineFactory`，把 `OpencodeClient` 迁移为 `OpencodeEngine`。**纯改名/纯移动，行为零变化，测试保持绿**——这是换内核的插入点，本任务不引入任何并发语义或业务逻辑变化。

## context

- `docs/20260813-AgentEngine多内核引擎改造方案.md` §2 目标架构、§3 协议定义、§5 公共能力下沉、§6 波次 A0、§7 决策点
- `docs/plan/tasks/harness-01.md`（本任务细化其「拆分」部分的第一步）
- 根 `AGENTS.md` 验证建议（后端测试与 CI 对齐）

## path

- `code/sewpg-bid-backend/app/services/opencode_client.py`（迁移原点，2817 行）
- 新建 `code/sewpg-bid-backend/app/services/agent_engine/` 包：
  - `base.py`（协议 + `ToolCompletedEvent` / `EngineRunResult` 类型）
  - `factory.py`（`AgentEngineFactory`，按 `AGENT_ENGINE` 环境变量实例化，默认 `opencode`）
  - `opencode_engine.py`（`OpencodeEngine`，原 `OpencodeClient` 全体方法迁入）
  - `json_utils.py` / `trace.py` / `errors.py`（§5 公共能力下沉，纯移动）
- 16 个调用方更新导入（见现状清单）
- 相关测试文件导入更新
- `docs/anbc_doc/架构总览/modules/opencode_client.md` 卡片与 `_data/bid_parse.json` 同步

## 现状（代码证据）

- `OpencodeClient` 定义于 `app/services/opencode_client.py:35`，2817 行，引擎传输与业务编排两层职责混合。
- 调用方 16 处：`parsing.py:36`、`outline_generation.py:26`、`technical_fact_curator.py:27`、`business_assembly.py:23`、`business_document_service.py:27`、`business_gap_planning.py:28`、`business_material_splitter.py:29`、`business_template_extractor.py:11`、`business_wiki_generation.py:47`、`bid_parse_service.py:45`、`tech_assembly.py:1598`、`technical_chat_service.py:14`、`technical_gap_ai_fill.py:20`、`technical_wiki_preview_generation.py:574,593`、`material_tag_import_fuzzy.py:129`、`material_certificate_time.py:1161`（后五处为函数内延迟导入）。
- 公共能力现状位置：`_repair_json_payload:2655` `_parse_json_payload:2518` `_balanced_json_object_candidates:2549`（→ `json_utils.py`）；`_build_output_trace:2760` `_coerce_timestamp:2781` `_normalize_output_parts:2792`（→ `trace.py`）；`_format_response_error:2619` `is_model_not_found_error:2639` `_short_http_error:2644`（→ `errors.py`）。行号以改造方案文档 §5 为准，实施时以实际为准。

## 改造方案

1. 新建 `app/services/agent_engine/` 包。`base.py` 定义 `AgentEngine` 协议（`create_session` / `run_session` / `list_messages` / `abort_session` / `delete_session`）与 `ToolCompletedEvent`、`EngineRunResult` 类型。
   - **同步起步**（方案 §7 已拍板）：A0 阶段协议用同步签名，与现状行为一致；async 化是 engine-03（B1）的事，届时协议再翻成 async。`base.py` 注释中注明 §3 的 async 目标形态。
   - `run_session` 对应现状 `_send_prompt_with_session_polling` 的通用形态；`on_tool_completed` 回调在 engine-02 落地，本任务可先以 `early_tool_command: str` 参数保留现状语义（不改行为）。
2. `OpencodeClient` 整体迁入 `opencode_engine.py` 并改名 `OpencodeEngine`；所有 `run_bid_*` / `generate_*_with_trace` 方法名与签名保持不动（外部调用方 16 处只改 import）。删除旧 `opencode_client.py`（不留兼容别名，import 全部指向新路径）。
3. §5 公共能力下沉：`json_utils.py` / `trace.py` / `errors.py` 纯移动（函数体不改），`OpencodeEngine` 改为引用。
4. `factory.py`：`AGENT_ENGINE` 环境变量（默认 `opencode`）→ 引擎实例；`codex`/`pi` 暂抛 `NotImplementedError`（engine-07/08 落地）。注意遵守根 AGENTS.md 配置分层：代码默认值本地安全。
5. 更新模块卡片与 `_data/bid_parse.json` 的 loc/调用链。

## verification

- 与 CI 对齐跑测试：
  ```bash
  cd code/sewpg-bid-backend
  APP_STORE_BACKEND=memory \
  DATABASE_URL="postgresql+asyncpg://biduser:bidpass@localhost:5432/bidplatform" \
  .venv/bin/python -m pytest -m "not integration" tests/ -k "opencode or outline or parsing or fact"
  ```
  全量 `-m "not integration"` 也要跑，失败集合与基线（Dev_20260813_rebase 起点）比对不得新增。
- `git diff` 审查：只应出现类名/导入路径/文件移动变化，无逻辑改动。
- 提交前 `git diff --check`。
