# AgentEngine 多内核引擎改造方案（2026-08-13）

> 目标：把「后端 → AI agent 内核」这一跳，从「写死在 `OpencodeClient`（2817 行）里的 opencode HTTP 协议」，收敛成一个**引擎无关的 `AgentEngine` 接口**，使 opencode / Codex / Pi 成为可插拔实现。
> 上游结论：`docs/anbc_doc/架构总览/05-Harness基建.md`（11 项短板）、`docs/plan/analysis/20260812-系统性重构.md`（harness-01 已立项但只到「拆分」粒度）、`docs/anbc_doc/架构总览/opencode-链路与替换可行性示意.html`（替换可行性与 5 个接口面）。
> prior art：`harbor-framework/harbor` 的 `BaseAgent` / `BaseInstalledAgent` / `AgentFactory`（见 §5）。

---

## 1. 现状诊断（代码证据）

`app/services/opencode_client.py`（2817 行）把两层职责搅在一起：

| 层 | 内容 | 证据（行号） |
|---|---|---|
| **A. 引擎/传输（通用）** | 建会话、发 prompt、轮询监管、heartbeat、输出增量、abort、JSON 修复 | `create_session:64` `send_prompt:116` `send_text_prompt:161` `list_session_messages:821` `abort_session:834` `_send_prompt_with_session_polling:1073` `_repair_json_payload:2655` |
| **B. 业务编排（特判）** | 14 个 `run_bid_*_with_trace` / `generate_*_with_trace`、三套 finalize 等待、业务 JSON 抽取、业务 stall 报错 | `run_bid_tech_fact_curator_with_trace:628` 等；`_wait_for_s1_finalize_after_prompt_return:1528` `_wait_for_template_finalize_after_prompt_return:1627` `_wait_for_s2_outline_finalize_after_prompt_return:1727`；`_extract_*_json:863~1030`（14 个）；`_raise_s1/template/s2_outline_*_stalled:2356~2406` |

**三个实锤问题：**

1. **业务命令写死在通用轮询循环里**：`_send_prompt_with_session_polling` 内部 `if early_tool_command == "s1parse-finalize"` / `"btplnav-finalize"` / `"s2outline-finalize"`（`opencode_client.py:1179-1192`）。每加一类 agent 任务，公共客户端就要多一段 `if`——这就是短板 1「客户端巨石化、业务特判下沉」。
2. **三套 finalize 等待近乎重复**：S1 / 模板 / S2目录各写了一份「等 finalize 命令完成后收割」，逻辑同构、细节漂移。
3. **14 个业务 JSON 抽取器 + 3 个业务 stall 报错**都长在客户端里，换引擎时这些要么跟着走、要么重写。

**结论**：改造的本质 = 把 A/B 两层切开，A 收成 `AgentEngine` 接口，B 上移到业务编排层；**引擎与业务之间的边界，就是解耦的边界。**

---

## 2. 目标架构：三层 + 工厂 + 配置

```
业务 service（S1~S4）             只认「建会话 → 跑一个会话 → 拿结果/读产物」
        │
AgentOrchestrator（业务编排层）    持有 engine；注册 early_command + 完成判定 + JSON 抽取
        │
AgentEngine（协议/接口）           create_session / run_session / list_messages / abort / delete
        │
 ┌──────┼──────────────────┐
OpencodeEngine        CodexEngine        PiEngine
 (HTTP 轮询)          (exec 子进程)      (stdio RPC)
```

- **内核层（opencode/Codex/Pi）**：agent loop、工具执行、LLM 调用、沙箱——**不重写，只适配**。
- **AgentEngine 协议**：引擎无关的「会话 + 可监管」原语。
- **AgentOrchestrator**：业务编排——把今天长在客户端里的 `run_bid_*` / `_extract_*_json` / finalize 判定搬上来。
- **AgentEngineFactory**：按 `AGENT_ENGINE=opencode|codex|pi` 实例化（对照 Harbor 的 `AgentFactory` + `AgentName` 枚举）。
- **配置分层**：`AGENT_ENGINE` 默认 `opencode`；5090 实测取值只落 `docker-compose.5090.yml`（遵守根 `AGENTS.md` 发布分工）。

---

## 3. AgentEngine 协议定义（目标形态，async）

```python
# app/services/agent_engine/base.py
from typing import Protocol, Callable

@dataclass
class ToolCompletedEvent:
    command: str        # 受控命令名，如 "s1parse-finalize"
    stdout: str         # 命令完整 stdout
    is_terminal: bool = False   # 由业务判定后回填，引擎不判断业务语义

@dataclass
class EngineRunResult:
    session_id: str
    reply_text: str
    tool_outputs: list[ToolCompletedEvent]
    trace: dict[str, Any]        # opencodeOutput 等价物，供前端留痕

class AgentEngine(Protocol):
    engine_name: str    # "opencode" | "codex" | "pi"

    async def create_session(self, title: str) -> str: ...
    async def run_session(
        self,
        session_id: str,
        prompt_text: str,
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
        tools: dict[str, bool] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,  # 进度增量
        on_tool_completed: Callable[[ToolCompletedEvent], bool] | None = None,  # 返回 True = 提前收割
        cancel_check: Callable[[], bool] | None = None,
    ) -> EngineRunResult: ...
    async def list_messages(self, session_id: str) -> list[dict[str, Any]]: ...
    async def abort_session(self, session_id: str) -> bool: ...
    async def delete_session(self, session_id: str) -> None: ...
```

**关键设计——early completion 从「命令字符串特判」变成「事件 + 判定回调」：**

- 引擎只负责**检测「一个 bash 工具完成了」**，上报 `ToolCompletedEvent{command, stdout}`——这是通用能力。
- 业务通过 `on_tool_completed` 决定「这个命令完成是否代表整轮结束」：`s1parse-finalize` 的 terminal 判定（`_s1_finalize_output_is_terminal`）是**业务知识**，留在 `AgentOrchestrator`，不进引擎。

这样短板 1 消失：新增一类 agent 任务 = 注册一个 `early_command + 判定函数`，不再改引擎。

> 注：现状 `send_prompt` 的 `provider/model` 每次请求可指定（`opencode_client.py:124-128` payload 带 `{providerID, modelID}`），协议保留该能力；Codex/Pi 落地时若「按请求切 provider」不支持，则在该引擎实现内降级为「会话级固定 provider」并显式记录（见 §6 风险）。

---

## 4. 三引擎实现设计

### 4.1 OpencodeEngine（HTTP，现状迁移）

- 复用现有 HTTP 传输：`POST /session`、`POST /session/{id}/message`、`GET /session/{id}/message`。
- `run_session` = 泛化后的 `_send_prompt_with_session_polling`：把 `early_tool_command: str` 换成 `on_tool_completed` 回调；删除 `:1179-1192` 的三段业务 `if`；`_find_completed_bash_tool_output` 改成上报 `ToolCompletedEvent`。
- 三套 `_wait_for_*_finalize` 收敛成一套通用「等命令完成」逻辑，差异点（terminal 判定、stall 报错文案）通过回调/参数注入。

### 4.2 CodexEngine（exec 子进程 + JSON 事件流）

借 Harbor 的 `BaseInstalledAgent` 模式：

- `run()` = 拼 `codex exec ... --json --resume <id>` 命令 → `subprocess.Popen` 子进程 → 流式读 stdout JSON 事件。
- `CLI_FLAGS` / `ENV_VARS` 映射：把 `reasoning_effort`、模型、`--skip-git-repo-check` 等配置映射成 Codex 参数（对照 Harbor `Codex.CLI_FLAGS`）。
- `ErrorPattern`：把 Codex 的 CLI 错误输出归类成统一异常（对齐现状 `_format_response_error`）。
- 会话模型：**一个 session ≈ 一个 exec 进程**；`abort` = kill 进程；`resume` = `--resume` 续跑。多会话 = 多进程（需进程池/超时回收，见 §6）。
- 早期收割：Codex 事件流结构化，`ToolCompletedEvent` 直接由 bash 工具调用事件映射，**比 HTTP 轮询更实时**（复用 4.1 的 `on_tool_completed` 语义）。

### 4.3 PiEngine（stdio RPC）

- 用 Pi 的 **RPC 模式**（JSON-over-stdio 常驻服务，与 `opencode serve` 最神似）：起一个 RPC 进程，按 JSON 命令驱动、事件流推送。
- 会话模型：**多会话 = 多进程**；`abort` = 发 RPC 停止命令或杀进程。
- 事件协议简单直接，但**重试/监管/超时回收要自己补齐**（周边能力，如 heartbeat、idle 超时，复用 `AgentEngine` 层抽出的公共监管器，见 §5）。

---

## 5. 引擎无关的公共能力下沉

以下今天长在客户端里、但**与引擎无关**的能力，抽成共享工具，三个引擎复用：

| 能力 | 现状位置 | 目标位置 |
|---|---|---|
| JSON 修复/解析 | `_repair_json_payload:2655` `_parse_json_payload:2518` `_balanced_json_object_candidates:2549` | `agent_engine/json_utils.py` |
| 输出轨迹留痕 | `_build_output_trace:2760` `_coerce_timestamp:2781` `_normalize_output_parts:2792` | `agent_engine/trace.py` |
| 监管器（heartbeat / idle 超时 / 进度增量） | `_send_prompt_with_session_polling` 内联 | `agent_engine/monitor.py`（一个 `SessionMonitor`，三引擎复用） |
| 错误归一化 | `_format_response_error:2619` `is_model_not_found_error:2639` `_short_http_error:2644` | `agent_engine/errors.py` |

抽掉这些后，`OpencodeEngine` 只保留「HTTP 收发 + 会话轮询」，`CodexEngine`/`PiEngine` 只保留「子进程/RPC 收发 + 事件映射」——引擎实现本身会很小。

---

## 6. 改造波次（映射现有 harness 任务 + 新增换内核任务）

| 波次 | 步骤 | 内容 | 对应 | 依赖 | 风险 |
|---|---|---|---|---|---|
| **A 边界+泛化** | A0 | 定义 `AgentEngine` 协议 + 类型 + `AgentEngineFactory`；`OpencodeClient` → `OpencodeEngine`（纯改名，行为不变，测试保持绿） | 细化 harness-01 | — | 低 |
| | A1 | early_completion 泛化：删 `:1179-1192` 业务 `if`，三套 `_wait_for_*_finalize` 收敛，`on_tool_completed` 回调机制 | harness-01 的「early_tool_command 注册」 | A0 | 中（长任务行为，需回归） |
| **B 异步+治理** | B1 | `OpencodeEngine` 异步化：`httpx.AsyncClient` + asyncio，去 daemon 线程 | harness-06 | A0 | 中 |
| | B2 | send_prompt 中途重试/断线恢复 | harness-03 | B1 | 中 |
| | B3 | 会话生命周期回收：`delete_session` + `opencode_data` 卷清理 | harness-04 | A0 | 低 |
| | B4 | 并发治理统一：三套信号量池收敛为单一预算，配置化章节并行度 | harness-02 | — | 中 |
| **C 换内核 PoC** | C1 | `CodexEngine` 实现（exec + 事件流 + resume + ErrorPattern） | **新增** | A1 | 中 |
| | C2 | `PiEngine` 实现（stdio RPC + 多进程 + 周边补齐） | **新增** | A1 | 中偏小 |
| | C3 | PoC：选 S1 分片会话 `run_tender_parse_shard_with_trace`（依赖最少链路）跑通 Codex/Pi | **新增**（对应可行性 html 第 1 步） | C1/C2 | — |
| **D 安全** | D1 | opencode 端口鉴权 + `deploy.resources` 限额 | harness-05 | — | 低 |

**顺序要点：**

- **A 波次是换内核的唯一前置**——不先立 `AgentEngine` 边界，C 就是重写而非接入。
- B 与 C **可并行**（B 改的是 OpencodeEngine 内部实现，C 新增两个独立引擎，路径不重叠）。
- C3 的 PoC 结论决定 `AGENT_ENGINE` 何时进入生产；PoC 前 `AGENT_ENGINE` 恒为 `opencode`。

---

## 7. 决策点（开工前拍板）

| 决策点 | 影响 | 建议 |
|---|---|---|
| `AgentEngine` 同步还是异步起步 | A 波次范围 | **同步起步**（A0 纯改名无行为变化），异步放 B1；若强行 A0 就上 async，A0 从「纯重构」变「重构+并发语义变更」，回归面骤增 |
| 业务编排层放哪 | A1 结构 | 新建 `app/services/agent_engine/orchestrator.py`；`run_bid_*` 方法名保持不动（外部调用方 14+ 处，见 §1 调用方清单），只换内部实现 |
| 进程型引擎（Codex/Pi）的会话池上限与超时回收 | C | 复用 `SessionMonitor`，但「一个 session 一个进程」需显式进程池上限 + 孤儿进程回收，与 harness-02 的并发预算合并设计 |
| `AGENT_ENGINE` 默认值与 5090 取值 | C3 后 | 代码默认 `opencode`；5090 层若要切引擎，只写 `docker-compose.5090.yml`，不回流改默认 |

---

## 8. 验证（每波次对齐）

- **后端**（与 CI 对齐，`AGENTS.md` 验证建议）：
  ```bash
  cd code/sewpg-bid-backend
  APP_STORE_BACKEND=memory \
  DATABASE_URL="postgresql+asyncpg://biduser:bidpass@localhost:5432/bidplatform" \
  .venv/bin/python -m pytest -m "not integration" <相关测试文件>
  ```
- **A0 必须「测试保持绿」**：纯改名，`git diff` 只应看到类名/导入路径变化。
- **A1/B 必须回归长任务链路**：S1 解析、S2 目录、事实表填写三路各跑一次真实/样本任务，比对失败集合而非总数。
- **C3 PoC 判据**：Codex/Pi 在 S1 分片链路上，`reply` 与产物文件与 opencode 基线**语义等价**（不要求逐字一致）；记录事件协议版本、进程资源占用、超长会话表现。
- **前端**：本次不触碰页面，但引擎切换不应改变 SSE 进度形态，需对技术标目录 SSE 做一次冒烟。

---

## 9. 与现有 plan 的关系

- 本方案**细化并扩展** `docs/plan/analysis/20260812-系统性重构.md` 的 harness 波次：`harness-01` 拆成 A0+A1，`harness-06/03/04/02/05` 分别对应 B1/B2/B3/B4/D1。
- **新增** C1/C2/C3（Codex/Pi 适配 + PoC）——现有 plan 只立项到「客户端拆分」，未含实际换内核实现，本方案补齐。
- 建议落地动作：在 `docs/plan/tasks/` 下新增 `engine-*` 系列 handoff，或把 A0~D1 逐个细化成 handoff 后替换/扩充 `harness-01` 等条目（**待确认**）。

---

## 10. 一句话结论

换内核不是「改 base_url」，而是**把 `AgentEngine` 边界立起来**：内核（opencode/Codex/Pi）当可插拔件，业务编排层（今天的 14 个 `run_bid_*` + finalize 判定 + JSON 抽取）上移，引擎只剩「会话 + 可监管」的薄适配。**顺序上先做 A（边界+泛化），换内核才有干净的插入点；B/C 可并行。**
