# agent_engine

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/agent_engine/`（包，11 个模块 + `__init__`） |
| 层级 | 服务层 |
| 领域 | 解析与AI引擎 |
| 行数 | 4873（包合计） |

**职责**: 后端所有 LLM 调用的唯一出口（engine-01 起由 `opencode_client.py` 拆包）：引擎协议/工厂/编排/会话监管/并发预算/JSON 修复/轨迹留痕/错误归一，opencode HTTP 引擎与 codex/pi 进程引擎三实现。

## 模块划分
- `base.py`（164）：`AgentEngine` 协议 + `ToolCompletedEvent`/`EngineRunResult`/`EarlyCompletionPlan`（业务命令经 plan 注入，引擎内无业务字面量）。
- `factory.py`（50）：`AgentEngineFactory` 按 `AGENT_ENGINE` 环境变量实例化，默认 `opencode`。
- `orchestrator.py`（1283）：`AgentOrchestrator` 分片/任务编排、受控命令终态判定与 stdout 收割、stall 检测。
- `opencode_engine.py`（1362）：`OpencodeEngine`——opencode HTTP 引擎（建会话/发 prompt/轮询监管/断线重连），原 `OpencodeClient`。
- `codex_engine.py`（717）/ `pi_engine.py`（718）：codex/pi CLI 进程引擎（headless exec + resume）。
- `monitor.py`（93）：`SessionMonitor`——heartbeat/idle 超时/断线计时唯一实现（engine-07 F6 收敛点）。
- `concurrency.py`（88）：`ConcurrencyBudget`/`BudgetPool`，进程级单一 `AGENT_CONCURRENCY_BUDGET` 预算派生各池。
- `json_utils.py`（200）/ `trace.py`（70）/ `errors.py`（109）：JSON 修复解析 / 输出轨迹留痕 / 错误归一化。

## 调用链
- **上游**: `outline_generation`、`parsing`/`parse_s1_skill`、草拟/填写/Wiki 生成等 AI 类服务（两轨）。
- **下游**: opencode 容器 HTTP `:4096`；codex/pi 本地 CLI；`system_settings`（模型配置）。

## 中间数据与状态
- opencode 会话 session_id 与执行轨迹 `opencodeOutput` 随结果落运行态；并发预算进程级单例；Skill 大文件交换走共享数据卷，不经 HTTP 通道。
