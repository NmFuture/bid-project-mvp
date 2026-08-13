# engine-03 review 01

- 对象：task/engine-03 分支 commit `5f0f736`（33 文件 +610/−553）
- 任务：`docs/plan/tasks/engine-03.md`（OpencodeEngine 异步化，波次 B1）
- 设计依据：`docs/20260813-AgentEngine多内核引擎改造方案.md` §3（async 协议）、§6 B1；`docs/plan/tasks/harness-06.md`（现状证据与取消路径 contract）
- 复跑：`APP_STORE_BACKEND=memory DATABASE_URL=... .venv/bin/python -m pytest -m "not integration"` → **2274 passed, 30 deselected, 177.79s**，与基线一致，无新增失败。

## Findings

### F1. P2 · blocking — `_request_slot` 经 `asyncio.to_thread` 获取信号量，取消路径泄漏许可，可致全进程引擎调用永久阻塞

- 代码位置：`code/sewpg-bid-backend/app/services/agent_engine/opencode_engine.py:140-150`（`_request_slot`）、`:399-410`（`raise_if_cancelled` 中 `worker_task.cancel()`）
- 设计文档位置：`docs/plan/tasks/engine-03.md` 改造方案 3「行为保持」；`docs/plan/tasks/harness-06.md` verification「取消路径（abort/取消解析）行为不变」及连带注意「异步化后信号量改 asyncio.Semaphore」
- 机理：`asyncio.to_thread(self._request_slots.acquire)` 一旦 executor 线程开始运行 acquire 就无法被取消。当取消（用户取消解析 → `cancel_check` → `worker_task.cancel()`）落在 acquire 等待窗口内时，协程收到 CancelledError、`_request_slot` 的 `finally: release()` 不会执行，但底层线程最终仍会 acquire 成功——许可被永久吃掉且无人释放。泄漏随取消次数累积。
- 影响面：部署默认 `OPENCODE_MAX_CONCURRENCY=1`（`code/docker-compose.yml:44,147`），**一次泄漏即让该进程后续所有引擎 HTTP 调用永久阻塞**，只能重启恢复。触发场景现实存在：预算 1 时任意两个并发引擎使用（如 S1 解析 + 技术标对话/目录生成）必然排队，取消排队方即泄漏。基线同步实现的 daemon 线程阻塞在 acquire 上不可中断，最终会 acquire 并正常 release，无此泄漏——属于取消路径行为回退。
- 附带风险：排队等待的 acquire 会占用默认 executor 线程（`min(32, cpu+4)`），重度排队时与 `bid_parse_service.cancel`、`technical_chat` 等其它 `asyncio.to_thread` 用户争抢 executor。
- 建议：改为取消安全的获取（最小修法：`while not self._request_slots.acquire(blocking=False): await asyncio.sleep(0.1)` 轮询；或按 harness-06 连带注意提前换 asyncio 原语，与 B4 对齐），并补「取消发生在预算等待窗口」的回归测试。
- 判 blocking 的依据：违反任务 contract「行为保持 / 取消路径行为不变」，且在生产取值下后果是进程级挂死，不是理论边界。

### F2. P3 · non-blocking — stalled 漂移（开发者已自报）：对外语义等价，可接受

- 代码位置：`opencode_engine.py:455-476`（主循环 idle 路径）与 `:555-634`（prompt 返回后 grace 等待路径）；测试 `tests/test_opencode_engine.py:2125-2171` `test_s1_parse_stalled_running_read_reports_trace`
- 设计文档位置：`docs/20260813-AgentEngine多内核引擎改造方案.md` §5 监管器语义；harness-06 失败显式暴露要求
- 核对：两条路径都调用同一个业务注入回调 `early_completion.on_idle_stalled`，抛出同样的 `RuntimeError("opencode incomplete/stalled …")`，trace 字段（`status=stalled`、`sessionId`、`lastTool/lastToolStatus/lastToolInput`）由同一回调构建，测试断言逐条保持。唯一差异：主循环 idle 路径 raise 前先 `abort_session`（彼时消息请求仍在飞），grace 路径不 abort——但 grace 路径进入条件是 prompt 已返回（worker task 已结束），服务端会话空闲，无 abort 必要。completionSource/failureReason 等可观测语义不变，判等价。
- 漂移根因属测试力学：异步化后 `time.monotonic` 与事件循环同源，worker（`asyncio.sleep(2)`）在主循环累计超过 idle 阈值前已完成，主循环退出后由 grace 路径判定 stalled。

### F3. P3 · non-blocking — `test_idle_timeout_aborts_session_and_joins_worker` 中线程回收断言已成死断言

- 代码位置：`tests/test_opencode_engine.py:1457-1459`，仍断言 `threading.enumerate()` 中不存在 `opencode-message-ses-idle-abort` 线程
- 异步化后该线程根本不会被创建，断言恒真、丧失区分度（测试名 `..._joins_worker` 语义也已过时）。同测试对 abort 调用与 idle timeout 异常的断言仍有效，故非形同虚设。建议删除该断言或改为断言 worker task 已被收割（`worker_task.done()`）。

### F4. P3 · non-blocking — 两条新关键路径无直接测试覆盖

- 代码位置：`opencode_engine.py:386-392`（worker 异常收 `error_holder`，标了 `# pragma: no cover`）+ `:656-659`（主协程 raise error_holder）；`:140-150`（`_request_slot` 并发预算获取）
- 代码审查确认两处逻辑正确（worker `except Exception` 兜底使 task 不带未消费异常，不会触发 "Task exception was never retrieved"），但「worker 异常如实抛给主协程」与「预算等待/释放」均无任何测试区分度。F1 的修法落地时应一并补测。

### F5. P3 · non-blocking（遗留偏差，非本任务引入）— `AgentEngine` 协议与 `OpencodeEngine` 实现结构仍不一致

- 代码位置：`code/sewpg-bid-backend/app/services/agent_engine/base.py:112-138` 协议定义为 `run_session/list_messages/delete_session`、`create_session -> str`；实现侧 `opencode_engine.py` 为 `send_prompt/list_session_messages`、`create_session -> dict`，且无 `delete_session`；`factory.py:22` `create() -> AgentEngine` 的注解实际不成立（Protocol 非 runtime_checkable，运行时不报错，静态检查会报）
- 设计文档位置：`docs/20260813-AgentEngine多内核引擎改造方案.md` §3 协议定义
- engine-03 只是把协议与实现两侧同步翻成 async，未扩大 A0/A1 已有的方法名/返回类型偏差；但 C 波次接 Codex/Pi 前必须对齐，否则工厂返回类型会误导新引擎实现者。

## 已核对通过的要点（无问题）

- **轮询 task 收割**：worker 异常收进 `error_holder` 由主协程显式 raise（`:386-392`、`:658-659`）；取消路径显式 `cancel + suppress(CancelledError) + await` 收割（`:406-409`）；`_wait_worker_stop` 用 `wait_for(shield(task), timeout)` 对齐原 `thread.join(timeout)` 语义，shield 不会误杀 worker。无未消费异常泄漏路径。
- **AsyncClient 生命周期**：全部按请求 `async with` 创建/关闭（`:171-177`、`:236-241`、`:304-305`、`:320-321`），与基线一致，无连接泄漏；类 docstring 对「引擎实例跨事件循环复用、不持有长连接」的论证成立。
- **行为保持**：0.5s 轮询节奏、heartbeat 间隔与计数、idle 判定、进度增量 signature 去重、grace 等待、`wait_after_prompt_return`、`assistant_stop_validator` 接力链路逐行仅 await 化；`send_prompt` 仍先排队再建 client（不消耗模型超时）；`create_session` 重试的 `time.sleep` → `await asyncio.sleep`。
- **桥接点**：`file_utils.run_awaitable_sync` 在事件循环本线程调用时显式 close 协程并 raise（`file_utils.py:46-68`），不存在「循环线程上静默阻塞调引擎」的路径；`technical_chat_service.chat` 经既有 `asyncio.to_thread` 进桥接（`technical_chat_service.py:225`）；`bid_parse_service.cancel` 新增 `asyncio.to_thread(self.cancel_parse, ...)` 方向正确；`parsing._run_coroutine_blocking` 保持原 `_run_async_ocr` 语义（无 loop 直接 `asyncio.run`，有 loop 开新线程独立循环 join）。
- **残留检查**：`app/` 下无 `threading.Thread(daemon=True)` 轮询残留（仅剩 file_utils/parsing 两处桥接用 join 线程，非轮询）；`_OPENCODE_REQUEST_SLOTS` 保留 `threading.BoundedSemaphore` 系 commit 声明的刻意留 B4（但获取方式引入 F1）；生产代码无新增 stub/mock/fake；17 个外围调用方与外围测试文件均为纯形态适配，无超范围改动。
- **表征测试**：`test_agent_engine_finalize_chains.py` 9 个用例仅适配异步调用形态（IsolatedAsyncioTestCase/AsyncMock/`asyncio.sleep` patch 目标替换），断言内容全部未动。
- **测试复跑**：2274 passed 与基线一致（见文首）。

## 结论

**blocked**。F1（P2 blocking）：取消路径的并发预算许可泄漏违反 engine-03/harness-06 的「行为保持 / 取消路径行为不变」contract，部署默认预算 1 时单次触发即进程级挂死，需在合入前修复并补回归测试。其余 F2–F5 为 P3 非阻塞，可与 F1 修复一并处理或留后续波次。
