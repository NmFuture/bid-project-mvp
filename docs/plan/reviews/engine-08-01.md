# engine-08 review 01（PiEngine / f18b219）

> **复验（2026-08-13，fix commit `8feb7f6`）**：P2-1、P2-2 均已修复，见下方各条目标注；
> 抽查复跑 `tests/test_pi_engine.py` **25 passed**（原 23 + 新增 2）。最终结论维持 **pass**。

- 评审对象：commit `f18b219`（`pi_engine.py` 新建 626 行、`factory.py` +6/-3、`tests/test_pi_engine.py` 新建 540 行 / 23 用例）
- 对照：`base.py` AgentEngine 协议（§3）、改造方案 §4.3 / §6 C2 / §7、pi-mono 官方 `packages/coding-agent/docs/rpc.md` 及源码（`cli/args.ts`、`packages/agent/src/types.ts`，2026-08-13 main）
- 复跑：worktree 内全量 `pytest -m "not integration"`：**2299 passed, 0 failed**（183s），与开发者声称一致

## 结论：**pass**（无 blocking；2 条 P2 建议在本冲刺内修掉，PoC 前必须复核）

## 核对通过的要点

- **协议契约**：五方法签名/返回类型与 `base.py` `AgentEngine` 严格一致（`create_session -> str`、`run_session(...) -> EngineRunResult`、`list_messages`、`abort_session -> bool`、`delete_session -> None`、`engine_name = "pi"`）。
- **on_tool_completed 语义**：引擎只检测「bash 工具完成」并上报 `ToolCompletedEvent`，回调返回 True 才收割；收割以回调返回后事件当前的 `stdout` 为准（`pi_engine.py:535-540` + run 循环 `:230` 读 `state.harvested.stdout`），与 `base.py:21-23` docstring 及 opencode 语义一致；`isError` 的工具完成不上报，对齐 opencode 非零 exit 跳过。
- **RPC 正确性**：per-request Future + `pending` 表关联；reader `finally` 对全部 pending `set_exception`（`:427-431`），乱序响应经 id 路由、迟到响应因 pending 已弹出落入 events 被忽略（无副作用）；`_rpc` 超时/写失败均清理 pending 并抛 RuntimeError，无泄漏挂死路径。`\r` 剥离与坏行容错（`:406-420`）符合 JSONL 约定。
- **进程回收**：`_terminate_session` 先 pop 进程表保证幂等（`:346-348`）；abort RPC（5s 超时，失败仅告警）→ kill → shield(wait) 10s 兜底告警 → cancel reader 并 await，顺序与兜底正确；终态路径（error/收割/取消/idle/进程意外退出）全覆盖回收；正常 settled 不杀进程、由 `delete_session` 回收，与一次 run 一进程的会话模型 docstring 自洽。
- **事件映射**：text/thinking delta 累计、`tool_execution_start/update/end` 字段（toolCallId 关联、partialResult 为累计值直接替换，与 rpc.md 一致）、`ToolCompletedEvent.event_id = session:toolCallId:command` 可去重、`auto_retry_end(success=false)` 报错，均与官方文档逐项吻合。`extension_ui_request` 仅对 `{select, confirm, input, editor}` 四个对话方法自动回 `cancelled`，与 rpc.md「dialog methods 阻塞等响应」的分类完全一致，headless 下合理。
- **CLI 参数**：`-n`（`--name`，设置会话显示名）、`--mode rpc`、`--no-session`、`--provider/--model` 均经 `cli/args.ts` 源码确认存在。
- **factory.py**：改动最小（注册 pi 分支 + 文案），默认引擎恒为 `opencode`，符合根 AGENTS.md 配置分层。
- **范围**：无 stub/mock 泄入生产路径（`_spawn_process` 注点有注释说明）；未超任务范围；`monitor.py` 未抽公共监管器属任务书允许的选项，dev 已在模块 docstring 显式记录「刻意不抽，留待三引擎统一」。

## Findings

### P2-1（non-blocking，**已修复 @ 8feb7f6**）：协议快照记录含不实事件 `agent_settled`

- 位置：`pi_engine.py:20`（docstring）、`:544-549`
- 事实：核对 pi-mono 官方 `docs/rpc.md` 与 `packages/agent/src/types.ts` 的 `AgentEvent` 联合类型（2026-08-13 main），事件表中**不存在 `agent_settled`**；运行终态事件就是 `agent_end`，且 `agent_end` 载荷只有 `messages`，**没有 `willRetry` 字段**（`willRetry` 在 `auto_compaction_end` 上）。docstring 注释「以 rpc.md 快照为准 agent_settled 必发」不成立。
- 影响：功能不受影响——`:547` 的 `agent_end and not willRetry` 兜底在真实协议下恒真，settled 判定实际靠它；`agent_settled` 分支是死代码。但「事件协议版本显式记录」是任务要求，记录内容有误会在升级 Pi 核对时误导。
- 建议：修正 docstring 与 `:548` 注释（终态 = `agent_end`；`willRetry` 判断可删或注明来源字段），PoC（engine-09）真实联通时复核事件序列。

### P2-2（non-blocking，**已修复 @ 8feb7f6**）：stdout 行缓冲默认 64KiB 上限，大输出会让 reader 异常退出

- 位置：`pi_engine.py:338`（`create_subprocess_exec` 未传 `limit`）、`:405`（`readline`）
- 事实：asyncio 子进程流默认 `limit=2**16`。`tool_execution_end`/`message_end` 单条 JSONL 携带完整 bash stdout，而本引擎的收割载荷恰恰就是 finalize 命令的完整 stdout；超过 64KiB 时 `readline` 抛 `ValueError`，reader 走通用异常分支退出，run 以「进程意外退出（returncode=None）」报错——进程其实活着，错误文案也误导。
- 建议：`create_subprocess_exec(..., limit=...)` 显式放大（如 8~16MiB），或 catch 后给出准确报错。单测无法覆盖（fake 无此限制），PoC 用大输出用例验证。

### P3-1（non-blocking）：run 进行中外部 `abort_session` 不会立刻终止 `run_session`

- 位置：`pi_engine.py:469-475`（`_process_exit` 且 `terminating=True` 时不置 error）、`:345` pop 后 run 循环仍持有 session
- 外部 abort 后 run 循环只收到一条「正常收尾」事件，此后无新事件，要等 idle 超时（默认 300s）才以 `RuntimeError(idle timeout)` 退出，语义与取消不符。当前编排层取消走 `cancel_check`，影响面小，但建议 `_process_exit` 非 settled 时无论 terminating 与否都让 run 尽快退出（或显式抛 abort 语义错误）。

### P3-2（non-blocking）：`session.events` 全生命周期只增不减

- 位置：`pi_engine.py:432-434`、`:455`
- 长会话多次 run 后事件缓冲无限增长（含完整工具输出文本）。一次 run 一进程的实际用法下风险低，建议在 run 结束或新 run 开始时截断。

### P3-3（non-blocking）：`create_session` 传空 title 时真实 pi 会退出

- 位置：`pi_engine.py:148`（`-n str(title or "")`）
- pi `main.ts` 对 `--name ""` 报 error 并 `exit(1)`，表现为握手失败。当前编排层均传非空标题，仅作鲁棒性备注（可省略空 title 的 `-n`）。

### P3-4（non-blocking）：测试覆盖缺口（不阻断）

- `test_pi_engine.py` 23 用例覆盖面良好（收发/映射/收割/回收/超时/取消/UI 取消/工厂），fake 子进程保真度合理。未覆盖：乱序/迟到响应、run 中途 RPC 超时、CRLF/坏行容错（代码有实现无测试）。建议 PoC 前补 1~2 条。

## 复验记录

- `git show f18b219` 全量 diff 逐行核对（本文件上述行号基于 worktree HEAD）。
- 官方协议核对来源：`docs/rpc.md`、`src/cli/args.ts`、`packages/agent/src/types.ts`（earendil-works/pi @ main，2026-08-13）。
- 全量测试复跑：worktree `code/sewpg-bid-backend`，CI 对齐环境变量，**2299 passed / 0 failed / 30 deselected**。

## 复验（fix commit `8feb7f6`，2026-08-13）

- **P2-1 已修复**：docstring 改为「`agent_end` 为运行终态、载荷无 `willRetry`、官方无 `agent_settled`」；两处分支注释改为防御写法说明；功能代码未动（符合修复建议）。
- **P2-2 已修复**：新增 `PI_RPC_STREAM_LIMIT_BYTES = 8MiB` 常量（注释说明动机），`create_subprocess_exec(..., limit=...)` 显式传入；补 2 条单测（limit 传参断言、256KiB 单行载荷完整收割）。大输出用例经 fake 验证折叠逻辑，真实 readline 上限仍留 PoC 复核（与常量注释一致）。
- 抽查复跑 `tests/test_pi_engine.py`：**25 passed**（原 23 + 新增 2）；开发者报全量 2301 passed / 0 failed，未重跑全量。
- 新 commit 未引入新问题；P3-1~P3-4 维持 non-blocking 留待后续。
- **最终结论：pass**（P2 清零，P3 不阻断）。
