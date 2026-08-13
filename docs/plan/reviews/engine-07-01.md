# engine-07 review 01

- 对象：task/engine-07 分支 commit `3587b39`（3 文件 +1134/−3）
- 任务：`docs/plan/tasks/engine-07.md`（CodexEngine 实现，波次 C1）
- 设计依据：`docs/20260813-AgentEngine多内核引擎改造方案.md` §3（协议）、§4.2（CodexEngine 设计）、§6 C1、§7（进程池上限与超时回收决策）
- 复跑：`APP_STORE_BACKEND=memory DATABASE_URL=... .venv/bin/python -m pytest -m "not integration"` → **2299 passed, 30 deselected, 107 subtests passed, 181.78s**，与开发者声称（基线 2276 + 新增 23）一致，无新增失败。

## Findings

### F1. P1 · blocking — 正常退出路径在读 `returncode` 前未 `wait()`，成功运行可被误判为「codex exec 失败（exit None）」

- 代码位置：`code/sewpg-bid-backend/app/services/agent_engine/codex_engine.py:306-307`（stdout EOF `break`）、`:338-347`（`returncode = process.returncode` 后直接判 `!= 0` 抛错）；`wait()` 只在 `finally` 的 `_reap_process`（`:467-476`）里发生，晚于判定。
- 机理：asyncio 的 `process.returncode` 由 child watcher 异步回填（macOS 默认 ThreadedChildWatcher：waitpid 在辅助线程完成后 `call_soon_threadsafe` 回事件循环）。进程退出时 stdout EOF 与 watcher 回调近乎同时排队， `_read_stderr`（`:483-490`）在 stderr 已 EOF 时不挂起直接返回，随后读到的 `returncode` 仍可能是 `None`。`None != 0` 为真 → 走 `_classify_failure` 抛 `codex exec 失败（exit None）`。这是**正常完成的主路径**（EOF break 是进程退出时最常见的出循环方式），不是边角分支；表现为成功运行被间歇性误判失败。`finally` 兜底仍会收尸，无僵尸，但结果错了。
- 测试为何没抓到：fake 的 `_FakeStdout.readline` 在 EOF 时**同步**写 `returncode`（`tests/test_codex_engine.py:45-46`），抹平了真实 asyncio「watcher 异步回填」的时序，这类竞态单测结构上看不到。
- 建议：EOF break 后先 `await self._wait_reaped(process)`（或 `process.wait()`）再读 `returncode`；fake 侧把 returncode 回填改为经事件循环回调（如 `loop.call_soon`），补一个「EOF 时 returncode 尚未回填」的回归用例。
- 判 blocking 的依据：核心路径正确性缺陷，触发概率非忽略量级；engine-09 真实联通 PoC 会直接撞上且表象（exit None）极具误导性。修复成本一行。

### F2. P2 · non-blocking — stderr 管道运行期间不排干，子进程 stderr 写满管道缓冲会假停滞直至 idle 超时被误杀

- 代码位置：`codex_engine.py:161`（`stderr=asyncio.subprocess.PIPE`）与 `:338`（`_read_stderr` 仅在事件泵结束后才读）。
- 机理：运行期间没有任何协程读 stderr。codex CLI 若向 stderr 输出超过管道缓冲（POSIX 通常 64KB），子进程阻塞在 write 上 → stdout 不再产事件 → 泵侧判 idle，最坏等满 `idle_timeout`（clamp 上限 900s）后按「假死」kill。不会死锁泄漏（idle 兜底 + finally reap 都在），但会把可正常完成的运行变成超时失败，且报错文案（idle timeout）掩盖真实原因。
- 建议：起一个伴随 task 持续 drain stderr 到内存 buffer（有界截断），进程终态后 join；或在 `_read_stderr` 之外加并发 reader。可与 F1 修复一并落地。

### F3. P3 · non-blocking — ERROR_PATTERNS 裸词过宽，存在误归类（仅影响失败文案，不杀可重试错误）

- 代码位置：`codex_engine.py:83-94`。
- 核对：`401` 裸数字会命中 "4010" 之类的端口/编号；`insufficient` 会命中 "insufficient permissions"（实为权限问题而非额度）。但归类只发生在**已经终态失败**之后（turn.failed / 非零退出），只改写报错文案，不参与重试决策，不存在「错杀可重试错误」。`is_model_not_found_error` 复用 `errors.py` 公共归一化，顺序优先于自有模式表，方向正确。建议把 `401` 加词边界（如 `\b401\b`）、`insufficient` 收窄为 `insufficient (quota|funds|credits)`。

### F4. P3 · non-blocking — 实例未配 `model_id` 时按请求传入的 `model_id` 被静默忽略（无 warning）

- 代码位置：`codex_engine.py:247`：warning 条件是 `model_id and self.model_id and model_id != self.model_id`，实例未配模型时 `run_session(model_id=...)` 走默认模型且不记任何日志。
- 与 commit message / 模块 docstring「传入值与实例配置不一致时记 warning 并忽略」的显式记录承诺略有出入。一行条件补齐即可。

### F5. P3 · non-blocking — 两个小防御缺口（当前编排层不触发，记录在案）

- 同会话并发 `run_session` 无防护：`state.process` 会被后一次 run 覆盖（`codex_engine.py:170`），此后 `abort_session`/`delete_session` 只能杀到后一个进程（前一个仍由自己的 `finally` 回收，不泄漏，但 abort 语义失真）。orchestrator 目前按会话串行调用，属防御缺口非现网 bug。
- prompt 未加 `--` 分隔（`:222` `argv.append(prompt_text)`）：以 `-` 开头的 prompt 会被 CLI 当 flag 解析。业务 prompt 为生成的中文文本，实际风险近零；若 codex CLI 支持 `--`，加上更稳。

### F6. P3 · non-blocking — heartbeat/idle 监管与 opencode_engine 内联实现重复，公共监管器未抽出

- 任务书允许「如公共监管器已抽出则复用，否则本任务落地」——`agent_engine/` 下尚无 `monitor.py`（方案 §5 目标），本任务选择内联落地合规。但 heartbeat 节奏、idle 判定、进度增量已与 `opencode_engine.py` 的内联版本形成第二份拷贝，后续波次（engine-06 并发预算 / PiEngine）落地时应按方案 §5 收敛为 `SessionMonitor`，避免三引擎各自漂移。此处只记不留债主张。

## 已核对通过的要点（无问题）

- **协议契约严格一致**：`create_session/run_session/list_messages/abort_session/delete_session` 五方法签名与返回类型逐字对齐 `base.py:112-138` 的 `AgentEngine` Protocol（含全部 keyword-only 参数）；`engine_name = "codex"`；factory `create() -> AgentEngine` 注解成立。
- **ToolCompletedEvent / on_tool_completed 语义对齐 opencode**：失败命令（exit_code 非 0/None）不上报（`:427-428`，口径同 `iter_completed_bash_tool_events:103-104`）；回调可改写 `event.stdout` 且收割结果以改写后为准（`:443-448`）；回调 True = 立即 kill 收割（`:328-331`）；`event_id` 稳定可去重；shell 包装剥离（`_extract_shell_command`）使 command 首词口径与 opencode bash 工具一致；`list_messages` 产出可被 `iter_completed_bash_tool_events` 原样消费（有专门用例 `:257-273`）。cancel 抛 `ParseCancelledError("解析已取消。")` 与 `opencode_engine.py:415/700` 逐字一致。
- **进程回收路径**：正常终态 / 提前收割 / cancel / abort / delete / idle 超时 / 异常，七条路径全部经 `finally: _reap_process`（kill + wait 收尸）或显式 `_terminate_process`；`_terminate_process` 幂等（returncode 检查 + `suppress(ProcessLookupError)`）；`_reap_process` 用 `wait_for(shield(wait), 5s)` 宽限后 kill，shield 不会误杀 wait 协程。abort 与泵并发时两边都置 `state.process = None` 且对同一 process 对象操作，无双重 kill 竞态。
- **CLI_FLAGS / ENV_VARS / 注入安全**：`create_subprocess_exec` 传 argv 列表，无 shell 拼接，prompt 作为独立 argv 元素，无注入面；空值不产参（`test_unset_optional_config_emits_no_extra_flags` 验证）；`sandbox_mode` 默认 `workspace-write` 本地安全，符合根 AGENTS.md 配置分层。
- **provider/tools 降级**：按方案 §3 注降级为实例级固定 + warning + 模块 docstring 显式记录（F4 仅一处条件缺口）。
- **测试质量**：fake 子进程能区分对错——收割/cancel/abort/delete/idle 五条路径均断言 `killed + waited` 且 `hang=True` 模拟假死进程，非「怎么都过」；`_ExecHarness` 记录 argv/env 验证参数拼装；23 用例覆盖事件映射、提前收割（含回调改写 stdout）、错误归类 4 分支、abort/delete/cancel/idle 回收、resume、降级、factory 三分支。
- **生产路径无 stub/mock/fake 残留**；`factory.py` 改动最小（+4/−3，docstring 同步）；无超任务范围改动。
- **测试复跑**：2299 passed 与声称一致（见文首）。

## 结论（初验，2026-08-13）

**blocked**。F1（P1 blocking）：正常退出路径的 returncode 竞态会把成功运行间歇性误判为 `codex exec 失败（exit None）`，属核心路径正确性缺陷，须先修（一行 `wait` + fake 时序修正）再合入。F2（stderr 排干）建议与 F1 一并修；F3–F6 非阻塞，可随修复一并处理或留后续波次。

---

## 复验（fix commit `2d9f4a8`，2026-08-13）

### F1 已修复 ✓（blocking 解除）

- EOF break 后先 `await self._reap_process(process)`（内含 `wait()` 收尸，returncode 由 child watcher 回填完成）再读退出码（`codex_engine.py` 事件泵尾部），时序正确；`state.process = None` 同步落位。路径化最坏情形（stdout 关、进程仍挂 stderr）由 reap 的 5s 宽限 + kill 兜底，无无界挂起。
- fake 改 `call_soon` 异步回填 returncode，真实还原 watcher 时序；回归用例 `test_eof_waits_for_async_returncode_backfill` 断言 `eof_returncode_was_none`（竞态窗口确实被制造）+ `waited` + 成功结果——把修复回滚掉该用例必红，区分度成立。

### F2 已修复 ✓

- `_drain_stderr` 伴随 task 按 4096 分块持续排干，sink 超 32KB 摊还截断到 8KB 尾部，内存有界；`_join_stderr_drain` 在 finally 中 join（shield + 5s 上限 + cancel 兜底 + 异常 suppress），生命周期无泄漏、无未消费 task 异常。排干 task 与 stdout 泵无共享状态，无新竞态。回归用例 `test_stderr_is_drained_during_run` 用 ~104KB stderr（超 64KB 管道缓冲）验证正常完成。

### F3 / F4 已修复 ✓ 无副作用

- F3：`\b401\b` / `\b429\b` / `insufficient (quota|funds|credits)` 词边界收窄；旧归类用例（"429 rate limit"、"401 Unauthorized"）仍命中，新增 `test_error_patterns_do_not_over_match` 验证 "4010" 端口与 "insufficient permissions" 走通用兜底。
- F4：warning 条件改为 `model_id and model_id != self.model_id`，实例未配模型时报「CLI 默认」；`test_request_model_without_instance_model_still_warns` 验证 warning 与 argv 不带 `--model`。等值传入不重复告警，无行为回退。

### 复验测试

- 抽查 `tests/test_codex_engine.py`：**27 passed**（23 + 新增 4）；全量 2303 passed 采信开发者自报（与 2299 + 4 口径一致）。
- F5（并发 run 防护 / `--` 分隔）、F6（monitor 收敛）维持 P3 留后续波次，不阻塞。

## 最终结论

**pass**。F1/F2 修复正确且有带区分度的回归用例，F3/F4 顺带收敛无副作用；F5/F6 为 P3 非阻塞遗留。engine-07 可合入，真实联通性验证按任务书留 engine-09 PoC。
