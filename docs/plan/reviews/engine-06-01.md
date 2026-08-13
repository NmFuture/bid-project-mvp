# engine-06 review 01

- 任务：docs/plan/tasks/engine-06.md（B4 并发治理统一——单一全局预算，各池派生）
- 产出：commit bbd64f9（12 文件 +592/-67）
- 复跑：`APP_STORE_BACKEND=memory ... pytest -m "not integration"` → **2364 passed, 0 failed, 30 deselected**（246s）。
  与开发者声称「2364 passed 0 failed」一致；新增 tests/test_agent_concurrency_budget.py 13 用例全绿。

## Findings

### P1（blocking）

无。

### P2（blocking）

1. **pi `create_session` 握手窗口的 asyncio 取消会双泄漏（预算许可 + 进程）**
   位置：`pi_engine.py:192-199`。
   握手 `await self._rpc(session, {"type": "get_state"}, ...)` 的失败清理写的是
   `except Exception`，而 `asyncio.CancelledError` 自 3.8 起继承 BaseException——
   create_session 任务在握手窗口被取消时，不走 `_terminate_session`：会话留在
   `_sessions`、pi 进程继续跑、预算许可永不归还。且 session_id 尚未返回给调用方，
   事后无人能补 delete，泄漏是永久的。重复触发可耗尽 `AGENT_CONCURRENCY_BUDGET`，
   把所有引擎（含 opencode）排队挂死——正是 engine-03 F1 防的那类事故，而本任务的
   核心验收就是「取消不泄漏」。进程孤儿部分是该路径旧有形态，但许可泄漏是本次并入
   预算后新增的共享资源泄漏。修复是一行级：握手段改 `except BaseException` 或
   try/finally 兜底 `_terminate_session`。`run_session`（`pi_engine.py:244` 起）同样
   无 try/finally，run 期间的 asyncio 取消也不回收；但调用方持有 session_id、编排层
   有 finally 回收可兜底，严重性低于 create_session 路径，建议同一次修掉。
   注：codex/pi 尚未接入生产解析链路（engine-09 PoC 待派发），所以不定 P1；但本任务
   宣称「取消落在等待窗口不泄漏（engine-03 F1 语义保持）」，留着这条已知取消泄漏路径
   不应合入。

### P2（non-blocking）

2. **部署行为变化：compose 默认 1 → 8，既有部署的旧变量静默失效**
   位置：`code/docker-compose.yml:44/:147`、`code/.env.example:41`、`code/.env.airgap.example:47`。
   无旧值回落的理由成立且已显式记录（commit message + `config.py:150-154` 注释：
   旧 OPENCODE_MAX_CONCURRENCY 只限默认槽一个池，当预算回落会把 S1 分片压回串行）。
   但两个后续动作缺失：
   - 既有部署 .env 里的 `OPENCODE_MAX_CONCURRENCY=1` 升级后变死变量，预算静默落到
     默认 8——并发 1→8 是行为跳变，需要在晋级 PR 描述 / 发布说明里显式告知运维改配。
   - `docker-compose.5090.yml` 无任何 CONCURRENCY/BUDGET 条目（已 grep 确认），5090
     此前经 compose 主层默认得到的有效值是 1，本次随之变 8。按根 AGENTS.md 配置分层，
     5090 的取值应由发布负责人在 5090 层定——要么晋级时在 5090.yml 补
     `AGENT_CONCURRENCY_BUDGET` 取值，要么确认 5090 .env 已锚定。代码默认 8 本身
     可辩护（预算现在覆盖 S1 分片池，默认 7，预算取 1~2 会把分片压串行），但与
     harness-02「代码默认值取 1~2」的建议相悖，属于有意偏离，需任务 Owner 知悉。

### P3（non-blocking）

3. **架构文档漂移**
   位置：`docs/anbc_doc/架构总览/opencode-链路与替换可行性示意.html:106/:257`、
   `docs/anbc_doc/架构总览/05-Harness基建.md:65/:71`。
   仍以 OPENCODE_MAX_CONCURRENCY（默认 1）/ 三池互不知晓为「现状」。harness-02 作为
   历史证据不动是合理的；这两份架构总览属现状描述，建议后续波次顺手更新，不阻塞。

4. **测试覆盖小缺口**
   13 用例覆盖面整体良好（见「核查结论」4），未覆盖：pi 握手失败（Exception 路径）
   归还许可、codex run 进行中（spawn 之后）取消的许可归还、以及 P2-1 的握手取消路径。
   前两条路径读代码确认正确（codex 外层 finally / pi `_terminate_session` finally），
   但缺对应用例，修复 P2-1 时建议一并补。

## 核查结论（针对 review 要点）

1. **两段获取正确性**：成立。`BudgetPool.acquire(blocking=False)` 预算许可→cap 顺序获取，
   cap 满立即归还预算许可，两段之间纯同步、无 await，无窗口（concurrency.py:71-79）。
   成对释放逐路径核过：opencode `_request_slot`（opencode_engine.py:171-176）轮询期不持许可、
   try/finally 释放，取消语义零改动；codex `run_session`（codex_engine.py:168-199）外层
   finally 覆盖 spawn 失败/泵事件取消/回收异常全路径；pi spawn 失败两个 except 分支均归还
   （pi_engine.py:173-180），`_terminate_session` pop 在前 + finally 归还，幂等且只归还一次
   （重复 delete 返回 False 不再 release）。唯一例外即 P2-1 的握手取消路径。
   blocking acquire 在等 cap 时持有预算许可：当前不存在嵌套获取（已核实每个引擎实例经
   `request_slots` 注入只用一个池；章节/分片 worker 各自把池注入 OpencodeEngine 构造器，
   单次请求一取一还），无循环等待，无死锁；未来若引入嵌套获取需重审此顺序。
2. **派生关系与语义变化**：三池 + codex/pi 进程池全部 `AGENT_CONCURRENCY_BUDGET.derive()`
   （concurrency.py:88 单例），总量恒 ≤ 预算成立；cap 被预算钳制（`min(cap, total)`）。
   compose 两处 `:-8` 与代码默认 8、两个 env 示例 =8 对齐；5090 层未动（见 P2-2 的跟进缺口）。
   `_OPENCODE_REQUEST_SLOTS` 名字保留作导出入口，tests/旧调用方兼容。
3. **codex/pi 进程池纳入**：codex 许可区间 = spawn 前→`_reap_process` 后，一个许可一个
   exec 进程，create_session 只登记不占许可（合理，进程尚不存在）；pi 许可区间 =
   create_session spawn 前→`_terminate_session` 归还，握手失败（Exception）经 terminate
   归还。除 P2-1 外无泄漏路径。
4. **测试质量**：13 用例覆盖三池同源、cap 钳制、过释放 ValueError、cap 满回滚不占坑、
   混合并发总量不超发（断言 `max_inflight == 3` 防空转）、跨事件循环/跨线程复用、
   opencode/codex/pi 等待窗口取消不泄漏、codex 完成归还、pi 占用到 terminate。
   自报竞态修复合理：取消用例 `sleep(0.3)` 覆盖 0.1s 轮询间隔，确定性足够。
5. **stub/超范围**：无 stub 残留；12 文件全部落在任务 path 清单内（bid_parse_service.py
   仅注释同步）；outline_generation.py / parsing.py 的 `threading` 导入仍有其他使用点，
   无死导入。
6. **复跑**：2364 passed / 0 failed / 30 deselected，与声称一致（基线 2351 + 新增 13）。

## 结论

**blocked**。仅 P2-1 一条 blocking：pi `create_session` 握手取消的许可泄漏，一行级修复
（`except BaseException` 或 try/finally 兜底 `_terminate_session`），建议同步处理
`run_session` 的同类路径并补对应用例。修完可直通，无需复审全量。P2-2 的部署告知与
5090 取值跟进随晋级流程走，P3 不阻塞。
